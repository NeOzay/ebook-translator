"""
Worker pour la Phase 1 du pipeline (traduction initiale + apprentissage glossaire).

Ce module gère la traduction initiale avec gros blocs (1500 tokens) et
l'apprentissage automatique du glossaire depuis les paires texte original/traduit.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from tqdm import tqdm

from ..logger import get_logger
from ..translation.engine import TranslationEngine, build_translation_map
from ..translation.parser import parse_llm_translation_output, validate_line_count
from ..config import TemplateNames
from ..correction.error_queue import ErrorItem

if TYPE_CHECKING:
    from ..llm import LLM
    from ..segment import Chunk
    from ..store import Store
    from ..glossary import Glossary
    from ..correction.error_queue import ErrorQueue

logger = get_logger(__name__)


class Phase1Worker:
    """
    Worker pour la Phase 1 : Traduction initiale avec apprentissage glossaire.

    Ce worker traduit des chunks de 1500 tokens en parallèle et apprend
    automatiquement le glossaire depuis les paires (original, traduit).

    En cas d'erreur de traduction :
    - Soumet l'erreur à ErrorQueue (non-bloquant)
    - Continue avec les autres chunks
    - Le CorrectionWorker tentera la correction en arrière-plan

    Attributes:
        llm: Instance LLM pour traduction
        store: Store pour sauvegarder traductions initiales
        glossary: Glossary pour apprentissage automatique
        error_queue: Queue pour soumettre erreurs (non-bloquant)
        target_language: Langue cible (ex: "fr")

    Example:
        >>> worker = Phase1Worker(llm, store, glossary, error_queue, "fr")
        >>> stats = worker.run_parallel(chunks, max_workers=4)
        >>> print(f"Translated: {stats['translated']}, Errors: {stats['errors_submitted']}")
    """

    def __init__(
        self,
        llm: "LLM",
        store: "Store",
        glossary: "Glossary",
        error_queue: "ErrorQueue",
        target_language: str,
    ):
        """
        Initialise le worker Phase 1.

        Args:
            llm: Instance LLM pour traduction
            store: Store pour sauvegarder traductions (initial_store)
            glossary: Glossary pour apprentissage automatique
            error_queue: Queue pour soumettre erreurs non-bloquantes
            target_language: Code langue cible (ex: "fr", "en")
        """
        self.llm = llm
        self.store = store
        self.glossary = glossary
        self.error_queue = error_queue
        self.target_language = target_language

        # Statistiques
        self.translated_count = 0
        self.errors_submitted = 0
        self.glossary_pairs_learned = 0

    def translate_chunk(self, chunk: "Chunk") -> bool:
        """
        Traduit un chunk (Phase 1) avec apprentissage glossaire.

        Flux :
        1. Vérifier cache
        2. Si manquant → appeler LLM
        3. Parser et valider sortie LLM
        4. Si erreur → soumettre à ErrorQueue (non-bloquant)
        5. Si succès → sauvegarder + apprendre glossaire

        Args:
            chunk: Chunk à traduire (1500 tokens)

        Returns:
            True si traduction réussie, False si erreur soumise à queue
        """
        try:
            # 1. Vérifier cache
            cached_translations, has_missing = self.store.get_from_chunk(chunk)

            if not has_missing:
                logger.debug(f"Chunk {chunk.index} déjà en cache (Phase 1)")
                # Même si en cache, apprendre glossaire si possible
                self._learn_glossary_from_chunk(chunk, cached_translations)
                return True

            # 2. Requête LLM
            source_content = str(chunk)
            prompt = self.llm.render_prompt(
                TemplateNames.First_Pass_Template,
                target_language=self.target_language,
                user_prompt=None,  # Phase 1 sans user_prompt
            )
            context = f"phase1_chunk_{chunk.index:03d}"
            llm_output = self.llm.query(prompt, source_content, context=context)
            translated_texts = parse_llm_translation_output(llm_output)

            # 3. Validation structurelle
            is_valid, error_message = validate_line_count(
                translations=translated_texts,
                source_content=source_content,
            )

            if not is_valid:
                # Soumettre erreur à la queue (non-bloquant)
                self._submit_missing_lines_error(
                    chunk, translated_texts, error_message or ""
                )
                return False

            # 4. Sauvegarder traductions
            translation_map = build_translation_map(chunk, translated_texts)
            for source_file, translations in translation_map.items():
                self.store.save_all(source_file, translations)

            # 5. Apprendre glossaire depuis paires
            self._learn_glossary_from_chunk(chunk, list(translated_texts.values()))

            self.translated_count += 1
            logger.debug(f"✅ Chunk {chunk.index} traduit (Phase 1)")
            return True

        except Exception as e:
            logger.exception(
                f"Erreur inattendue lors de la traduction du chunk {chunk.index}: {e}"
            )
            # Soumettre erreur générique à la queue
            self.error_queue.put(
                ErrorItem(
                    chunk=chunk,
                    error_type="missing_lines",
                    error_data={
                        "error_message": str(e),
                        "missing_indices": [],
                        "translated_texts": {},
                    },
                    phase="initial",
                )
            )
            self.errors_submitted += 1
            return False

    def _submit_missing_lines_error(
        self,
        chunk: "Chunk",
        translated_texts: dict[int, str],
        error_message: str,
    ) -> None:
        """
        Soumet une erreur de lignes manquantes à la queue.

        Args:
            chunk: Chunk avec erreur
            translated_texts: Traductions partielles reçues
            error_message: Message d'erreur de validation
        """
        from ..translation.parser import count_expected_lines

        source_content = str(chunk)
        expected_count = count_expected_lines(source_content)
        expected_indices = set(range(expected_count))
        actual_indices = set(translated_texts.keys())
        missing_indices = sorted(expected_indices - actual_indices)

        error_item = ErrorItem(
            chunk=chunk,
            error_type="missing_lines",
            error_data={
                "error_message": error_message,
                "expected_count": expected_count,
                "missing_indices": missing_indices,
                "translated_texts": translated_texts,
            },
            phase="initial",
        )

        self.error_queue.put(error_item)
        self.errors_submitted += 1
        logger.warning(
            f"⚠️ Chunk {chunk.index}: {len(missing_indices)} lignes manquantes → ErrorQueue"
        )

    def _learn_glossary_from_chunk(
        self,
        chunk: "Chunk",
        translated_texts: list[str],
    ) -> None:
        """
        Apprend le glossaire depuis les paires (original, traduit) du chunk.

        Utilise glossary.learn_pair() pour extraire automatiquement les termes
        (noms propres, acronymes, termes techniques) et leurs traductions.

        Args:
            chunk: Chunk avec textes originaux
            translated_texts: Liste des traductions (même ordre que chunk.fetch())
        """
        try:
            for (page, tag_key, original_text), translated_text in zip(
                chunk.fetch(), translated_texts
            ):
                if original_text and translated_text:
                    # Apprendre la paire (extraction automatique)
                    self.glossary.learn_pair(original_text, translated_text)
                    self.glossary_pairs_learned += 1

            logger.debug(
                f"📚 Glossaire appris depuis chunk {chunk.index} ({self.glossary_pairs_learned} paires)"
            )

        except Exception as e:
            logger.warning(f"Erreur lors de l'apprentissage glossaire: {e}")
            # Non-bloquant : ne pas faire échouer la traduction

    def run_parallel(
        self,
        chunks: list["Chunk"],
        max_workers: int = 4,
    ) -> dict:
        """
        Lance la traduction de tous les chunks en parallèle (Phase 1).

        Utilise ThreadPoolExecutor pour paralléliser les traductions.
        Les erreurs sont soumises à ErrorQueue sans bloquer.

        Args:
            chunks: Liste des chunks à traduire (1500 tokens chacun)
            max_workers: Nombre de threads parallèles (défaut: 4)

        Returns:
            Statistiques de la Phase 1 :
            {
                "translated": nombre de chunks traduits avec succès,
                "errors_submitted": nombre d'erreurs soumises à la queue,
                "glossary_pairs_learned": nombre de paires apprises,
                "total_chunks": nombre total de chunks
            }

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
                            pbar.write(
                                f"⚠️ Chunk {chunk.index}: Erreur soumise à ErrorQueue"
                            )
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
            "errors_submitted": self.errors_submitted,
            "glossary_pairs_learned": self.glossary_pairs_learned,
            "total_chunks": total_chunks,
        }

        logger.info(
            f"✅ Phase 1 terminée:\n"
            f"  • Traduits: {stats['translated']}/{total_chunks}\n"
            f"  • Erreurs soumises: {stats['errors_submitted']}\n"
            f"  • Paires glossaire apprises: {stats['glossary_pairs_learned']}"
        )

        return stats
