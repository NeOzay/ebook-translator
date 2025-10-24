"""
Worker pour la Phase 2 du pipeline (affinage avec glossaire).

Ce module gère l'affinage des traductions avec petits blocs (300 tokens),
en utilisant le glossaire appris en Phase 1 et la traduction initiale.

Note: La validation et sauvegarde sont désormais gérées par ValidationWorkerPool.
"""

from typing import TYPE_CHECKING

from tqdm import tqdm

from ..config import TemplateNames
from ..logger import get_logger
from ..translation.parser import parse_llm_translation_output

if TYPE_CHECKING:
    from ..glossary import Glossary
    from ..llm import LLM
    from ..segment import Chunk
    from ..stores.multi_store import MultiStore
    from ..validation import ValidationWorkerPool

logger = get_logger(__name__)


class Phase2Worker:
    """
    Worker pour la Phase 2 : Affinage avec glossaire.

    Ce worker affine les traductions initiales avec :
    - Segmentation fine (300 tokens) pour meilleur contrôle
    - Glossaire appris en Phase 1 injecté dans le prompt
    - Traduction initiale comme base pour amélioration

    Note: Validation et sauvegarde sont désormais gérées par ValidationWorkerPool.
    Ce worker se concentre uniquement sur :
    1. Récupérer traduction initiale
    2. Construire prompt enrichi (glossaire + initial)
    3. Requête LLM pour affinage
    4. Soumission à ValidationWorkerPool pour validation/sauvegarde

    Attributes:
        llm: Instance LLM pour affinage
        multi_store: MultiStore pour accès initial et refined
        validation_pool: Pool de workers pour validation/sauvegarde
        glossary: Glossary appris en Phase 1
        target_language: Langue cible

    Example:
        >>> worker = Phase2Worker(llm, multi_store, validation_pool, glossary, "fr")
        >>> stats = worker.run_sequential(chunks)
        >>> print(f"Refined: {stats['refined']}")
    """

    def __init__(
        self,
        llm: "LLM",
        multi_store: "MultiStore",
        validation_pool: "ValidationWorkerPool",
        glossary: "Glossary",
        target_language: str,
    ):
        """
        Initialise le worker Phase 2.

        Args:
            llm: Instance LLM pour affinage
            multi_store: MultiStore pour accès initial_store et refined_store
            validation_pool: Pool de workers pour validation/sauvegarde
            glossary: Glossary appris en Phase 1
            target_language: Code langue cible (ex: "fr", "en")
        """
        self.llm = llm
        self.multi_store = multi_store
        self.validation_pool = validation_pool
        self.glossary = glossary
        self.target_language = target_language

        # Statistiques
        self.refined_count = 0
        self.fallback_to_initial = 0

    def refine_chunk(self, chunk: "Chunk") -> bool:
        """
        Affine un chunk (Phase 2) et soumet pour validation.

        Flux simplifié :
        1. Récupérer traduction initiale (Phase 1)
        2. Exporter glossaire pour injection
        3. Construire prompt enrichi (refine.jinja)
        4. Appeler LLM pour affinage
        5. Soumettre à ValidationWorkerPool (validation + sauvegarde async)

        Args:
            chunk: Chunk à affiner (300 tokens)

        Returns:
            True si affinage LLM réussi, False si erreur (ex: traduction initiale manquante)
        """
        try:
            # 1. Récupérer traduction initiale (Phase 1)
            initial_translations, initial_missing = (
                self.multi_store.initial_store.get_from_chunk(chunk)
            )

            if initial_missing:
                logger.warning(
                    f"⚠️ Chunk {chunk.index}: Traduction initiale manquante (Phase 1 incomplète)"
                )
                self.fallback_to_initial += 1
                return False

            # 2. Formatter traduction initiale pour le prompt
            initial_translation = self._format_initial_translation(
                chunk, initial_translations
            )

            # 3. Exporter glossaire
            glossary_export = self.glossary.export_for_prompt(
                max_terms=50, min_confidence=0.5
            )

            # 4. Compter nombre de lignes attendues
            from ..checks.line_count_check import count_expected_lines

            source_content = str(chunk)
            expected_count = count_expected_lines(source_content)

            # 5. Construire prompt enrichi
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

            # 6. Appeler LLM
            context = f"phase2_chunk_{chunk.index:03d}"
            llm_output = self.llm.query(
                prompt, "", context=context
            )  # Pas de source_content, tout dans prompt

            # 7. Parser sortie LLM
            refined_texts = parse_llm_translation_output(llm_output)

            # 8. Soumettre à ValidationWorkerPool
            # La validation et sauvegarde seront faites en arrière-plan
            self.validation_pool.submit(chunk, refined_texts)

            self.refined_count += 1
            logger.debug(f"✅ Chunk {chunk.index} affiné et soumis pour validation (Phase 2)")
            return True

        except Exception as e:
            logger.exception(
                f"Erreur inattendue lors de l'affinage du chunk {chunk.index}: {e}"
            )
            return False

    def _format_initial_translation(
        self,
        chunk: "Chunk",
        initial_translations: dict[int, str],
    ) -> str:
        """
        Formatte la traduction initiale pour injection dans le prompt.

        Format :
        <0/>Traduction initiale ligne 0
        <1/>Traduction initiale ligne 1
        ...

        Args:
            chunk: Chunk avec textes originaux
            initial_translations: Dictionnaire {index: traduction} des traductions initiales

        Returns:
            Traduction formatée avec numéros de ligne
        """
        lines = []
        for i, translated_text in initial_translations.items():
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


    def run_sequential(self, chunks: list["Chunk"]) -> dict:
        """
        Lance l'affinage de tous les chunks séquentiellement (Phase 2).

        Phase 2 est séquentielle (pas de parallélisation) pour :
        - Garantir cohérence globale avec le glossaire
        - Réduire charge sur le LLM
        - Permettre ajustements manuels si nécessaire

        La validation et sauvegarde sont gérées en arrière-plan par ValidationWorkerPool.

        Args:
            chunks: Liste des chunks à affiner (300 tokens chacun)

        Returns:
            Statistiques de la Phase 2 :
            {
                "refined": nombre de chunks affinés avec succès,
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
                            f"⚠️ Chunk {chunk.index}: Traduction initiale manquante"
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
            "fallback_to_initial": self.fallback_to_initial,
            "total_chunks": total_chunks,
        }

        logger.info(
            f"✅ Phase 2 terminée:\n"
            f"  • Affinés: {stats['refined']}/{total_chunks}\n"
            f"  • Fallbacks Phase 1: {stats['fallback_to_initial']}\n"
            f"  Note: Validation en cours en arrière-plan (voir ValidationWorkerPool)"
        )

        return stats
