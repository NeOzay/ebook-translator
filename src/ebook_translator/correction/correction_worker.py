"""
Thread de correction dédié pour traiter les erreurs de traduction de manière asynchrone.

Ce module fournit un worker qui consomme une ErrorQueue et tente de corriger
les erreurs de traduction (lignes manquantes, fragment mismatch) sans bloquer
les threads de traduction principaux.
"""

import threading
import time
from typing import Optional, TYPE_CHECKING

from ..config import TemplateNames
from ..logger import get_logger
from .error_queue import ErrorQueue, ErrorItem

if TYPE_CHECKING:
    from ..llm import LLM
    from ..store import Store

logger = get_logger(__name__)


class CorrectionWorker:
    """
    Thread dédié qui consomme la queue d'erreurs et tente de les corriger.

    Ce worker tourne en arrière-plan et traite les erreurs de traduction
    dès qu'elles arrivent dans la queue, permettant aux threads de traduction
    de continuer sans attendre.

    Attributes:
        error_queue: Queue contenant les erreurs à corriger
        llm: Instance du LLM pour les retries
        store: Store actif (initial ou refined selon la phase)
        target_language: Langue cible de la traduction
        corrected_count: Nombre d'erreurs corrigées avec succès
        failed_count: Nombre d'erreurs non récupérables

    Example:
        >>> worker = CorrectionWorker(error_queue, llm, store, "fr")
        >>> worker.start()
        >>> # ... traductions en cours ...
        >>> worker.stop(timeout=10.0)
        >>> print(f"Corrected: {worker.corrected_count}, Failed: {worker.failed_count}")
    """

    def __init__(
        self,
        error_queue: ErrorQueue,
        llm: "LLM",
        store: "Store",
        target_language: str,
        worker_id: int = 0,
    ):
        """
        Initialise le worker de correction.

        Args:
            error_queue: Queue contenant les erreurs à corriger
            llm: Instance du LLM pour les retries
            store: Store pour sauvegarder les corrections
            target_language: Code de la langue cible (ex: "fr", "en")
            worker_id: Identifiant unique du worker (pour logs et debug)
        """
        self.error_queue = error_queue
        self.llm = llm
        self.store = store
        self.target_language = target_language
        self.worker_id = worker_id

        # Thread management
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Statistics
        self.corrected_count = 0
        self.failed_count = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        """
        Démarre le thread de correction en arrière-plan.

        Le thread est configuré en mode daemon pour s'arrêter automatiquement
        quand le programme principal se termine.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning(f"[Worker-{self.worker_id}] CorrectionWorker déjà démarré")
            return

        logger.info(f"🔧 [Worker-{self.worker_id}] Démarrage du thread de correction")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"CorrectionWorker-{self.worker_id}"
        )
        self._thread.start()

    def _run(self) -> None:
        """
        Boucle principale du thread de correction.

        Consomme la queue d'erreurs et tente de corriger chaque erreur.
        Continue jusqu'à réception du signal stop.
        """
        logger.debug(f"[Worker-{self.worker_id}] Thread de correction actif")

        while not self._stop_event.is_set():
            try:
                # Récupérer une erreur (timeout 1s pour vérifier stop_event régulièrement)
                item = self.error_queue.get(block=True, timeout=1.0)

                if item is None:
                    continue

                logger.debug(f"[Worker-{self.worker_id}] Traitement de {item}")
                self._correct_error(item)

            except Exception as e:
                # Timeout ou erreur inattendue
                if "Empty" not in str(type(e).__name__):
                    logger.exception(f"[Worker-{self.worker_id}] Erreur inattendue dans CorrectionWorker: {e}")
                continue

        logger.debug(f"[Worker-{self.worker_id}] Thread de correction arrêté")

    def _correct_error(self, item: ErrorItem) -> None:
        """
        Tente de corriger une erreur de traduction.

        Args:
            item: L'erreur à corriger
        """
        try:
            if item.error_type == "missing_lines":
                success = self._correct_missing_lines(item)
            elif item.error_type == "fragment_mismatch":
                success = self._correct_fragment_mismatch(item)
            else:
                logger.error(f"Type d'erreur inconnu: {item.error_type}")
                success = False

            if success:
                with self._lock:
                    self.corrected_count += 1
                self.error_queue.mark_corrected(item)
                logger.info(f"✅ [Worker-{self.worker_id}] Correction réussie: {item}")
            else:
                # Retry si pas encore atteint max_retries
                if item.retry_count < item.max_retries:
                    item.retry_count += 1
                    logger.warning(
                        f"⚠️ [Worker-{self.worker_id}] Correction échouée, retry {item.retry_count}/{item.max_retries}: {item}"
                    )
                    self.error_queue.put(item)  # Re-queue
                else:
                    with self._lock:
                        self.failed_count += 1
                    self.error_queue.mark_failed(item)
                    logger.error(
                        f"❌ [Worker-{self.worker_id}] Correction échouée après {item.max_retries} tentatives: {item}"
                    )

        except Exception as e:
            logger.exception(f"Erreur lors de la correction de {item}: {e}")
            with self._lock:
                self.failed_count += 1
            self.error_queue.mark_failed(item)

    def _correct_missing_lines(self, item: ErrorItem) -> bool:
        """
        Corrige une erreur de lignes manquantes.

        Args:
            item: ErrorItem avec error_type="missing_lines"

        Returns:
            True si correction réussie, False sinon
        """
        try:
            from ..translation.parser import (
                parse_llm_translation_output,
                validate_line_count,
                validate_retry_indices,
            )
            from ..translation.engine import build_translation_map

            chunk = item.chunk
            error_data = item.error_data
            missing_indices = error_data["missing_indices"]
            translated_texts = error_data["translated_texts"]

            # Construire le prompt de retry (CIBLÉ - seulement lignes manquantes)
            retry_prompt = self.llm.render_prompt(
                TemplateNames.Missing_Lines_Targeted_Template,
                target_language=self.target_language,
                error_message=error_data.get("error_message", ""),
                missing_indices=missing_indices,
                source_content=chunk.mark_lines_to_numbered(missing_indices),
            )

            logger.debug(
                f"Retry lignes manquantes: {len(missing_indices)} lignes (chunk {chunk.index})"
            )

            # Appel LLM
            context = f"correction_missing_chunk_{chunk.index:03d}"
            llm_output = self.llm.query(retry_prompt, "", context=context)
            missing_translated_texts = parse_llm_translation_output(llm_output)

            # Valider que le retry a fourni les bons indices
            is_retry_valid, retry_error = validate_retry_indices(
                missing_translated_texts, missing_indices
            )

            if not is_retry_valid:
                logger.warning(f"Retry invalide: {retry_error}")
                return False

            # Merger avec les traductions existantes
            translated_texts.update(missing_translated_texts)

            # Re-valider le compte total
            source_content = str(chunk)
            is_valid, error_message = validate_line_count(
                translations=translated_texts,
                source_content=source_content,
            )

            if not is_valid:
                logger.warning(f"Validation totale échouée: {error_message}")
                # Mettre à jour error_data pour le prochain retry
                item.error_data["error_message"] = error_message
                return False

            # Sauvegarder les traductions corrigées
            translation_map = build_translation_map(chunk, translated_texts)
            for source_file, translations in translation_map.items():
                self.store.save_all(source_file, translations)

            logger.debug(f"Lignes manquantes corrigées pour chunk {chunk.index}")
            return True

        except Exception as e:
            logger.exception(f"Erreur lors de la correction de lignes manquantes: {e}")
            return False

    def _correct_fragment_mismatch(self, item: ErrorItem) -> bool:
        """
        Corrige une erreur de fragment mismatch.

        Args:
            item: ErrorItem avec error_type="fragment_mismatch"

        Returns:
            True si correction réussie, False sinon
        """
        try:
            from .retry_engine import RetryEngine

            error_data = item.error_data
            original_fragments = error_data["original_fragments"]
            incorrect_segments = error_data["translated_segments"]
            original_text = error_data.get("original_text", "")

            # Utiliser RetryEngine existant
            retry_engine = RetryEngine(self.llm, max_retries=1)  # 1 seul retry ici
            result = retry_engine.attempt_correction(
                original_fragments=original_fragments,
                incorrect_segments=incorrect_segments,
                target_language=self.target_language,
                original_text=original_text,
            )

            if result.success and result.corrected_text:
                # Sauvegarder la correction
                page = error_data.get("page")
                tag_key = error_data.get("tag_key")

                if page and tag_key:
                    self.store.save(
                        page.epub_html.file_name,
                        tag_key.index,
                        result.corrected_text,
                    )
                    logger.debug(f"Fragment mismatch corrigé pour {tag_key}")
                    return True

            logger.warning("Correction de fragment mismatch échouée")
            return False

        except Exception as e:
            logger.exception(f"Erreur lors de la correction de fragment mismatch: {e}")
            return False

    def stop(self, timeout: float = 10.0) -> bool:
        """
        Arrête le thread de correction proprement.

        Attend que toutes les erreurs en cours soient traitées, puis arrête
        le thread. Si le timeout est atteint, force l'arrêt.

        Args:
            timeout: Temps d'attente maximum en secondes (défaut: 10.0)

        Returns:
            True si arrêt réussi dans le délai, False si timeout

        Example:
            >>> worker.stop(timeout=30.0)
            True
        """
        if self._thread is None or not self._thread.is_alive():
            logger.warning(f"[Worker-{self.worker_id}] CorrectionWorker déjà arrêté")
            return True

        logger.info(f"🛑 [Worker-{self.worker_id}] Arrêt du thread de correction...")
        self._stop_event.set()

        # Attendre que le thread se termine
        self._thread.join(timeout=timeout)

        if self._thread.is_alive():
            logger.error(
                f"⚠️ [Worker-{self.worker_id}] Thread de correction n'a pas pu s'arrêter dans le délai ({timeout}s)"
            )
            return False

        logger.info(f"✅ [Worker-{self.worker_id}] Thread de correction arrêté")
        return True

    def switch_store(self, new_store: "Store") -> None:
        """
        Change le store actif (pour passer de Phase 1 à Phase 2).

        Args:
            new_store: Le nouveau store à utiliser

        Example:
            >>> # Passer de Phase 1 à Phase 2
            >>> worker.switch_store(multi_store.refined_store)
        """
        logger.info(f"[Worker-{self.worker_id}] Changement de store: {id(self.store)} → {id(new_store)}")
        self.store = new_store

    def get_statistics(self) -> dict:
        """
        Récupère les statistiques du worker.

        Returns:
            Dictionnaire avec corrected_count et failed_count

        Example:
            >>> stats = worker.get_statistics()
            >>> print(f"Corrected: {stats['corrected']}, Failed: {stats['failed']}")
        """
        with self._lock:
            return {
                "corrected": self.corrected_count,
                "failed": self.failed_count,
                "is_alive": self._thread is not None and self._thread.is_alive(),
            }

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        stats = self.get_statistics()
        return (
            f"CorrectionWorker(\n"
            f"  corrected={stats['corrected']}, "
            f"  failed={stats['failed']}, "
            f"  is_alive={stats['is_alive']}\n"
            f")"
        )
