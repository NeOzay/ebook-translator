"""
Worker pour la Phase 2 du pipeline (affinage avec glossaire).

Ce module gère l'affinage des traductions avec petits blocs (300 tokens),
en utilisant le glossaire appris en Phase 1 et la traduction initiale.
"""

from typing import TYPE_CHECKING

from tqdm import tqdm

from ..logger import get_logger
from ..translation.engine import build_translation_map
from ..translation.parser import parse_llm_translation_output, validate_line_count
from ..config import TemplateNames
from ..correction.error_queue import ErrorItem

if TYPE_CHECKING:
    from ..llm import LLM
    from ..segment import Chunk
    from ..stores.multi_store import MultiStore
    from ..glossary import Glossary
    from ..correction.error_queue import ErrorQueue

logger = get_logger(__name__)


class Phase2Worker:
    """
    Worker pour la Phase 2 : Affinage avec glossaire.

    Ce worker affine les traductions initiales avec :
    - Segmentation fine (300 tokens) pour meilleur contrôle
    - Glossaire appris en Phase 1 injecté dans le prompt
    - Traduction initiale comme base pour amélioration
    - Validation structurelle + cohérence terminologique

    En cas d'erreur :
    - Soumet à ErrorQueue (non-bloquant)
    - Fallback sur traduction initiale si refined échoue

    Attributes:
        llm: Instance LLM pour affinage
        multi_store: MultiStore pour accès initial et refined
        glossary: Glossary appris en Phase 1
        error_queue: Queue pour erreurs non-bloquantes
        target_language: Langue cible

    Example:
        >>> worker = Phase2Worker(llm, multi_store, glossary, error_queue, "fr")
        >>> stats = worker.run_sequential(chunks)
        >>> print(f"Refined: {stats['refined']}, Fallbacks: {stats['fallback_to_initial']}")
    """

    def __init__(
        self,
        llm: "LLM",
        multi_store: "MultiStore",
        glossary: "Glossary",
        error_queue: "ErrorQueue",
        target_language: str,
    ):
        """
        Initialise le worker Phase 2.

        Args:
            llm: Instance LLM pour affinage
            multi_store: MultiStore pour accès initial_store et refined_store
            glossary: Glossary appris en Phase 1
            error_queue: Queue pour soumettre erreurs non-bloquantes
            target_language: Code langue cible (ex: "fr", "en")
        """
        self.llm = llm
        self.multi_store = multi_store
        self.glossary = glossary
        self.error_queue = error_queue
        self.target_language = target_language

        # Statistiques
        self.refined_count = 0
        self.errors_submitted = 0
        self.fallback_to_initial = 0

    def refine_chunk(self, chunk: "Chunk") -> bool:
        """
        Affine un chunk (Phase 2) avec glossaire et traduction initiale.

        Flux :
        1. Vérifier cache refined
        2. Si manquant → récupérer traduction initiale (Phase 1)
        3. Exporter glossaire pour injection
        4. Construire prompt enrichi (refine.jinja)
        5. Appeler LLM pour affinage
        6. Valider structure
        7. Si erreur → soumettre à ErrorQueue
        8. Si succès → sauvegarder dans refined_store

        Args:
            chunk: Chunk à affiner (300 tokens)

        Returns:
            True si affinage réussi, False si erreur soumise
        """
        try:
            # 1. Vérifier cache refined
            cached_refined, has_missing = self.multi_store.refined_store.get_from_chunk(
                chunk
            )

            if not has_missing:
                logger.debug(f"Chunk {chunk.index} déjà affiné (Phase 2)")
                return True

            # 2. Récupérer traduction initiale (Phase 1)
            initial_translations, initial_missing = (
                self.multi_store.initial_store.get_from_chunk(chunk)
            )

            if initial_missing:
                logger.warning(
                    f"⚠️ Chunk {chunk.index}: Traduction initiale manquante (Phase 1 incomplète)"
                )
                # Soumettre erreur pour que Phase 1 soit relancée via CorrectionWorker
                self._submit_missing_initial_error(chunk)
                return False

            # 3. Formatter traduction initiale pour le prompt
            initial_translation = self._format_initial_translation(
                chunk, initial_translations
            )

            # 4. Exporter glossaire
            glossary_export = self.glossary.export_for_prompt(
                max_terms=50, min_confidence=0.5
            )

            # 5. Compter nombre de lignes attendues
            from ..translation.parser import count_expected_lines

            source_content = str(chunk)
            expected_count = count_expected_lines(source_content)

            # 6. Construire prompt enrichi
            prompt = self.llm.render_prompt(
                TemplateNames.Refine_Template,
                target_language=self.target_language,
                initial_translation=initial_translation,
                glossaire=(
                    glossary_export
                    if glossary_export
                    else "Aucun terme dans le glossaire."
                ),
                expected_count=expected_count,
            )

            # 7. Appeler LLM
            context = f"phase2_chunk_{chunk.index:03d}"
            llm_output = self.llm.query(
                prompt, "", context=context
            )  # Pas de source_content, tout dans prompt
            refined_texts = parse_llm_translation_output(llm_output)

            # 8. Validation structurelle
            is_valid, error_message = validate_line_count(
                translations=refined_texts,
                source_content=source_content,
            )

            if not is_valid:
                # Soumettre erreur à la queue
                self._submit_missing_lines_error(
                    chunk, refined_texts, error_message or ""
                )
                return False

            # 9. Sauvegarder traductions affinées
            translation_map = build_translation_map(chunk, refined_texts)
            for source_file, translations in translation_map.items():
                self.multi_store.save_all_refined(source_file, translations)

            self.refined_count += 1
            logger.debug(f"✅ Chunk {chunk.index} affiné (Phase 2)")
            return True

        except Exception as e:
            logger.exception(
                f"Erreur inattendue lors de l'affinage du chunk {chunk.index}: {e}"
            )
            self.error_queue.put(
                ErrorItem(
                    chunk=chunk,
                    error_type="missing_lines",
                    error_data={
                        "error_message": str(e),
                        "missing_indices": [],
                        "translated_texts": {},
                    },
                    phase="refined",
                )
            )
            self.errors_submitted += 1
            return False

    def _format_initial_translation(
        self,
        chunk: "Chunk",
        initial_translations: list[str],
    ) -> str:
        """
        Formatte la traduction initiale pour injection dans le prompt.

        Format :
        <0/>Traduction initiale ligne 0
        <1/>Traduction initiale ligne 1
        ...

        Args:
            chunk: Chunk avec textes originaux
            initial_translations: Liste des traductions initiales

        Returns:
            Traduction formatée avec numéros de ligne
        """
        lines = []
        for i, translated_text in enumerate(initial_translations):
            if translated_text:
                lines.append(f"<{i}/>{translated_text}")
            else:
                # Si traduction manquante, utiliser texte original
                original_text = (
                    list(chunk.body.values())[i] if i < len(chunk.body) else ""
                )
                lines.append(f"<{i}/>{original_text}")
                logger.warning(
                    f"⚠️ Chunk {chunk.index}, ligne {i}: Traduction initiale manquante, utilisation de l'original"
                )

        return "\n".join(lines)

    def _submit_missing_lines_error(
        self,
        chunk: "Chunk",
        refined_texts: dict[int, str],
        error_message: str,
    ) -> None:
        """
        Soumet une erreur de lignes manquantes (Phase 2) à la queue.

        Args:
            chunk: Chunk avec erreur
            refined_texts: Traductions affinées partielles
            error_message: Message d'erreur de validation
        """
        from ..translation.parser import count_expected_lines

        source_content = str(chunk)
        expected_count = count_expected_lines(source_content)
        expected_indices = set(range(expected_count))
        actual_indices = set(refined_texts.keys())
        missing_indices = sorted(expected_indices - actual_indices)

        error_item = ErrorItem(
            chunk=chunk,
            error_type="missing_lines",
            error_data={
                "error_message": error_message,
                "expected_count": expected_count,
                "missing_indices": missing_indices,
                "translated_texts": refined_texts,
            },
            phase="refined",
        )

        self.error_queue.put(error_item)
        self.errors_submitted += 1
        logger.warning(
            f"⚠️ Chunk {chunk.index} (Phase 2): {len(missing_indices)} lignes manquantes → ErrorQueue"
        )

    def _submit_missing_initial_error(self, chunk: "Chunk") -> None:
        """
        Soumet une erreur car traduction initiale manquante.

        Args:
            chunk: Chunk sans traduction Phase 1
        """
        error_item = ErrorItem(
            chunk=chunk,
            error_type="missing_lines",
            error_data={
                "error_message": "Traduction initiale (Phase 1) manquante pour affinage",
                "missing_indices": list(range(len(chunk.body))),
                "translated_texts": {},
            },
            phase="initial",  # Doit être corrigé en Phase 1
        )

        self.error_queue.put(error_item)
        self.errors_submitted += 1
        self.fallback_to_initial += 1

    def run_sequential(self, chunks: list["Chunk"]) -> dict:
        """
        Lance l'affinage de tous les chunks séquentiellement (Phase 2).

        Phase 2 est séquentielle (pas de parallélisation) pour :
        - Garantir cohérence globale avec le glossaire
        - Réduire charge sur le LLM
        - Permettre ajustements manuels si nécessaire

        Args:
            chunks: Liste des chunks à affiner (300 tokens chacun)

        Returns:
            Statistiques de la Phase 2 :
            {
                "refined": nombre de chunks affinés avec succès,
                "errors_submitted": nombre d'erreurs soumises,
                "fallback_to_initial": nombre de fallbacks sur Phase 1,
                "total_chunks": nombre total de chunks
            }

        Example:
            >>> chunks = list(segmentator.get_all_segments())
            >>> stats = worker.run_sequential(chunks)
            >>> print(f"Phase 2: {stats['refined']}/{stats['total_chunks']} chunks")
        """
        total_chunks = len(chunks)
        logger.info(
            f"🎨 Phase 2: Démarrage affinage de {total_chunks} chunks (séquentiel)"
        )

        with tqdm(
            total=total_chunks,
            desc="Phase 2 (Affinage avec glossaire)",
            unit="chunk",
            ncols=100,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
        ) as pbar:
            for chunk in chunks:
                try:
                    success = self.refine_chunk(chunk)
                    if not success:
                        pbar.write(
                            f"⚠️ Chunk {chunk.index}: Erreur soumise à ErrorQueue"
                        )
                except KeyboardInterrupt:
                    pbar.write("\n❌ Phase 2 interrompue par l'utilisateur")
                    raise
                except Exception as e:
                    logger.exception(f"Erreur inattendue pour chunk {chunk.index}: {e}")
                    pbar.write(f"❌ Chunk {chunk.index}: Erreur inattendue")

                pbar.update(1)

        # Statistiques finales
        stats = {
            "refined": self.refined_count,
            "errors_submitted": self.errors_submitted,
            "fallback_to_initial": self.fallback_to_initial,
            "total_chunks": total_chunks,
        }

        logger.info(
            f"✅ Phase 2 terminée:\n"
            f"  • Affinés: {stats['refined']}/{total_chunks}\n"
            f"  • Erreurs soumises: {stats['errors_submitted']}\n"
            f"  • Fallbacks Phase 1: {stats['fallback_to_initial']}"
        )

        return stats
