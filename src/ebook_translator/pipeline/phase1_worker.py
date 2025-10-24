"""
Worker pour la Phase 1 du pipeline (traduction initiale + apprentissage glossaire).

Ce module gère la traduction initiale avec gros blocs (1500 tokens) et
l'apprentissage automatique du glossaire depuis les paires texte original/traduit.

Note: La validation et sauvegarde sont désormais gérées par ValidationWorkerPool.
"""

from ..store import Store
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from tqdm import tqdm

from ..config import TemplateNames
from ..logger import get_logger
from ..translation.parser import parse_llm_translation_output

if TYPE_CHECKING:
    from ..llm import LLM
    from ..segment import Chunk
    from ..validation import ValidationWorkerPool

logger = get_logger(__name__)


class Phase1Worker:
    """
    Worker pour la Phase 1 : Traduction initiale.

    Ce worker traduit des chunks de 1500 tokens en parallèle.
    L'apprentissage du glossaire est géré par ValidationWorkerPool via callback.

    Note: Validation et sauvegarde sont désormais gérées par ValidationWorkerPool.
    Ce worker se concentre uniquement sur :
    1. Vérification cache
    2. Requête LLM pour traduction si cache manquant
    3. Parsing de la sortie LLM
    4. Soumission à ValidationWorkerPool pour validation/sauvegarde/glossaire

    Attributes:
        llm: Instance LLM pour traduction
        store: Store initial pour vérification cache
        validation_pool: Pool de workers pour validation/sauvegarde
        target_language: Langue cible (ex: "fr")

    Example:
        >>> worker = Phase1Worker(llm, store, validation_pool, "fr")
        >>> stats = worker.run_parallel(chunks, max_workers=4)
        >>> print(f"Translated: {stats['translated']}")
    """

    def __init__(
        self,
        llm: "LLM",
        store: "Store",
        validation_pool: "ValidationWorkerPool",
        target_language: str,
    ):
        """
        Initialise le worker Phase 1.

        Args:
            llm: Instance LLM pour traduction
            store: Store initial pour vérification cache
            validation_pool: Pool de workers pour validation/sauvegarde
            target_language: Code langue cible (ex: "fr", "en")
        """
        self.llm = llm
        self.store = store
        self.validation_pool = validation_pool
        self.target_language = target_language

        # Statistiques
        self.translated_count = 0

    def translate_chunk(self, chunk: "Chunk") -> bool:
        """
        Traduit un chunk (Phase 1) et soumet pour validation.

        Flux simplifié :
        1. Requête LLM pour traduction
        2. Parser sortie LLM
        3. Soumettre à ValidationWorkerPool (validation + sauvegarde async)
        4. Apprendre glossaire

        Args:
            chunk: Chunk à traduire (1500 tokens)

        Returns:
            True si traduction LLM réussie, False si erreur parsing
        """
        try:
            # 1. Vérifier cache
            translated_texts, has_missing = self.store.get_from_chunk(chunk)

            if has_missing:
                # 2. Requête LLM
                source_content = str(chunk)
                prompt = self.llm.render_prompt(
                    TemplateNames.First_Pass_Template,
                    target_language=self.target_language,
                    user_prompt=None,  # Phase 1 sans user_prompt
                )
                context = f"phase1_chunk_{chunk.index:03d}"
                llm_output = self.llm.query(prompt, source_content, context=context)

                # 3. Parser sortie LLM
                translated_texts = parse_llm_translation_output(llm_output)

            # 4. Soumettre à ValidationWorkerPool
            # La validation et sauvegarde seront faites en arrière-plan
            # Le glossaire sera appris via callback après validation réussie
            self.validation_pool.submit(chunk, translated_texts)

            self.translated_count += 1
            logger.debug(
                f"✅ Chunk {chunk.index} traduit et soumis pour validation (Phase 1)"
            )
            return True

        except Exception as e:
            logger.exception(
                f"Erreur inattendue lors de la traduction du chunk {chunk.index}: {e}"
            )
            return False

    def run_parallel(
        self,
        chunks: list["Chunk"],
        max_workers: int = 4,
    ) -> dict:
        """
        Lance la traduction de tous les chunks en parallèle (Phase 1).

        Utilise ThreadPoolExecutor pour paralléliser les traductions LLM.
        La validation et sauvegarde sont gérées en arrière-plan par ValidationWorkerPool.

        Args:
            chunks: Liste des chunks à traduire (1500 tokens chacun)
            max_workers: Nombre de threads parallèles (défaut: 4)

        Returns:
            Statistiques de la Phase 1 :
            {
                "translated": nombre de chunks traduits avec succès,
                "total_chunks": nombre total de chunks
            }

            Note: Le glossaire est appris via callback ValidationWorkerPool

        Example:
            >>> chunks = list(segmentator.get_all_segments())
            >>> stats = worker.run_parallel(chunks, max_workers=4)
            >>> print(f"Phase 1: {stats['translated']}/{stats['total_chunks']} chunks")
        """
        total_chunks = len(chunks)
        logger.info(
            f"🚀 Phase 1: Démarrage traduction de {total_chunks} chunks ({max_workers} workers)"
        )

        with tqdm(
            total=total_chunks,
            desc="Phase 1 (Traduction initiale)",
            unit="chunk",
            ncols=100,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
        ) as pbar:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Soumettre toutes les tâches
                futures = {
                    executor.submit(self.translate_chunk, chunk): chunk
                    for chunk in chunks
                }

                # Attendre completion
                for future in as_completed(futures):
                    chunk = futures[future]
                    try:
                        success = future.result()
                        if not success:
                            pbar.write(f"⚠️ Chunk {chunk.index}: Erreur traduction LLM")
                    except KeyboardInterrupt:
                        pbar.write("\n❌ Phase 1 interrompue par l'utilisateur")
                        raise
                    except Exception as e:
                        logger.exception(
                            f"Erreur inattendue pour chunk {chunk.index}: {e}"
                        )
                        pbar.write(f"❌ Chunk {chunk.index}: Erreur inattendue")

                    pbar.update(1)

        # Statistiques finales
        stats = {
            "translated": self.translated_count,
            "total_chunks": total_chunks,
        }

        logger.info(
            f"✅ Phase 1 terminée:\n"
            f"  • Traduits: {stats['translated']}/{total_chunks}\n"
            f"  Note: Validation et apprentissage glossaire en cours en arrière-plan (voir ValidationWorkerPool)"
        )

        return stats
