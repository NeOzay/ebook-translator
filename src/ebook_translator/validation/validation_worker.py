"""
Worker thread pour valider et corriger les chunks avant sauvegarde.

Ce module fournit un worker qui consomme une ValidationQueue,
applique le pipeline de validation, et envoie vers SaveQueue si validé.
"""

import queue
import threading
import time
from typing import TYPE_CHECKING, Literal

from ..checks import ValidationContext, ValidationPipeline
from ..logger import get_logger
from .validation_queue import ValidationQueue, SaveQueue, SaveItem

if TYPE_CHECKING:
    from ..llm import LLM
    from ..segment import Chunk

logger = get_logger(__name__)


class ValidationWorker:
    """
    Thread worker qui valide et corrige les chunks avant sauvegarde.

    Ce worker consomme une ValidationQueue, applique le pipeline de validation
    avec corrections automatiques, et envoie vers SaveQueue si tous les checks passent.

    Architecture:
        ValidationQueue → ValidationWorker → SaveQueue → SaveWorker → Store

    Attributes:
        worker_id: Identifiant unique du worker
        validation_queue: Queue de chunks à valider
        save_queue: Queue pour envoyer chunks validés au SaveWorker
        pipeline: Pipeline de validation à appliquer
        llm: Instance LLM pour corrections
        target_language: Langue cible (ex: "fr")
        phase: Phase du pipeline ("initial" ou "refined")
        validated_count: Nombre de chunks validés avec succès
        rejected_count: Nombre de chunks rejetés

    Example:
        >>> worker = ValidationWorker(
        ...     worker_id=0,
        ...     validation_queue=validation_queue,
        ...     save_queue=save_queue,
        ...     pipeline=pipeline,
        ...     llm=llm,
        ...     target_language="fr",
        ...     phase="initial",
        ... )
        >>> worker.run()  # Boucle jusqu'au signal d'arrêt
    """

    def __init__(
        self,
        worker_id: int,
        validation_queue: ValidationQueue,
        save_queue: SaveQueue,
        pipeline: ValidationPipeline,
        llm: "LLM",
        target_language: str,
        phase: Literal["initial", "refined"],
        stop_event: threading.Event,
        max_retries: int = 1,
    ):
        """
        Initialise le worker de validation.

        Args:
            worker_id: Identifiant unique du worker (pour logs)
            validation_queue: Queue de chunks à valider
            save_queue: Queue pour envoyer chunks validés vers SaveWorker
            pipeline: Pipeline de validation à appliquer
            llm: Instance LLM pour corrections
            target_language: Code langue cible (ex: "fr", "en")
            phase: Phase du pipeline ("initial" ou "refined")
            stop_event: Event partagé pour signal d'arrêt (set() → arrêt immédiat)
        """
        self.worker_id = worker_id
        self.validation_queue = validation_queue
        self.save_queue = save_queue
        self.pipeline = pipeline
        self.llm = llm
        self.target_language = target_language
        self.phase: Literal["initial", "refined"] = phase
        self.stop_event = stop_event
        self.max_retries = max_retries

        # Statistiques
        self.validated_count = 0
        self.rejected_count = 0

    def run(self):
        """
        Boucle principale du worker.

        Consomme la ValidationQueue jusqu'à ce que stop_event soit set.
        Pour chaque item, valide et sauvegarde si OK, rejette sinon.

        Note:
            Utilise un timeout court (0.5s) pour permettre une réactivité rapide.
            Vérification stop_event à chaque timeout pour arrêt immédiat.
        """
        logger.info(f"[ValidationWorker-{self.worker_id}] Démarré")

        while not self.stop_event.is_set():
            try:
                # Attendre un item (timeout court pour réactivité)
                item = self.validation_queue.get(timeout=0.5)

            except queue.Empty:
                # Timeout - vérifier stop_event et continuer
                continue

            # Si item est None, c'est une erreur (ne devrait plus arriver avec stop_event)
            if item is None:
                logger.warning(
                    f"[ValidationWorker-{self.worker_id}] Reçu None (comportement déprécié, "
                    f"utiliser stop_event.set() à la place)"
                )
                continue

            # Valider et sauvegarder
            try:
                self._validate_and_save(item.chunk, item.translated_texts)
            except Exception as e:
                logger.exception(
                    f"[ValidationWorker-{self.worker_id}] Erreur lors de la validation: {e}"
                )

        logger.info(
            f"[ValidationWorker-{self.worker_id}] Arrêté "
            f"(validated={self.validated_count}, rejected={self.rejected_count})"
        )

    def _validate_and_save(self, chunk: "Chunk", translated_texts: dict[int, str]):
        """
        Valide un chunk et envoie vers SaveQueue si OK.

        Args:
            chunk: Chunk à valider
            translated_texts: Traductions à valider {line_index: translated_text}
        """
        # Construire original_texts depuis chunk.fetch()
        original_texts = {
            idx: original_text
            for idx, (_, _, original_text) in enumerate(chunk.fetch_body())
        }

        # Construire contexte de validation
        context = ValidationContext(
            chunk=chunk,
            translated_texts=translated_texts,
            original_texts=original_texts,
            llm=self.llm,
            target_language=self.target_language,
            phase=self.phase,
            max_retries=self.max_retries,
        )

        # Exécuter pipeline
        success, final_translations, results = self.pipeline.validate_and_correct(
            context
        )

        if success:
            # Préparer SaveItem pour sauvegarde asynchrone
            from ..translation.engine import build_translation_map

            translation_map = build_translation_map(chunk, final_translations)
            save_item = SaveItem(
                chunk=chunk,
                final_translations=final_translations,
                source_files=translation_map,
            )

            # Envoyer vers SaveQueue (SaveWorker s'en occupera)
            self.save_queue.put(save_item)

            # Logger les lignes filtrées si présentes
            if context.filtered_lines:
                self.rejected_count += 1
                self.validation_queue.mark_rejected()
                logger.warning(
                    f"[ValidationWorker-{self.worker_id}] ⚠️ {len(context.filtered_lines)} ligne(s) "
                    f"filtrée(s) pour chunk {chunk.index}:"
                )
                for filtered in context.filtered_lines:
                    logger.warning(
                        f"  • File: {filtered.file_name}, "
                        f"Line: {filtered.file_line}, "
                        f"Chunk: {filtered.chunk_index}, "
                        f"ChunkLine: {filtered.chunk_line}, "
                        f"Check: {filtered.check_name}, "
                        f"Reason: {filtered.reason}"
                    )
                logger.info(
                    f"[ValidationWorker-{self.worker_id}] ✅ Chunk {chunk.index} validé "
                    f"avec {len(final_translations)} ligne(s) sauvegardée(s) "
                    f"({len(context.filtered_lines)} filtrées)"
                )
            else:
                self.validated_count += 1
                self.validation_queue.mark_validated()
                logger.debug(
                    f"[ValidationWorker-{self.worker_id}] ✅ Chunk {chunk.index} validé "
                    f"et envoyé vers SaveQueue"
                )

        else:
            # Rejeter - ne pas sauver
            self.rejected_count += 1
            self.validation_queue.mark_rejected()

            # Logger les erreurs détaillées
            failed_checks = [r for r in results if not r.is_valid]
            error_summary = "\n".join(f"  • {r}" for r in failed_checks)

            logger.error(
                f"[ValidationWorker-{self.worker_id}] ❌ Chunk {chunk.index} rejeté "
                f"(échec validation après corrections):\n{error_summary}"
            )
