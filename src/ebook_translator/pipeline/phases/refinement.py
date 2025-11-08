"""
Phase 2: Raffinage avec glossaire et petits blocs.
"""

from pathlib import Path

from ebook_translator.pipeline.base import PhaseBase, ExecutionMode
from ebook_translator.pipeline.context import ChunkContext, PhaseContext, PhaseStats
from ebook_translator.pipeline.phases.initial_translation import InitialTranslationPhase
from ebook_translator.segmentation.segmentator import Chunk
from ebook_translator.config import TemplateNames
from ebook_translator.checks import (
    LineCountCheck,
    FragmentCountCheck,
    PunctuationCheck,
    SentenceCheck,
)
from ebook_translator.logger import get_logger

logger = get_logger(__name__)


class RefinementPhase(PhaseBase):
    """
    Phase 2: Raffinage avec glossaire (petits blocs, séquentiel).

    Configuration:
    - max_tokens: 300 (petits blocs pour contrôle fin)
    - overlap_ratio: 1.0 (100% = chaque chunk inclut le précédent en entier)
    - execution_mode: SEQUENTIAL (séquentiel pour cohérence)
    - template: translate_refine (avec glossaire + traduction initiale)

    Validation:
    - LineCountCheck: Toutes les lignes traduites
    - FragmentCountCheck: Nombre correct de séparateurs </>
    - PunctuationCheck: Paires de guillemets correctes

    Note: SentenceCheck est retiré (déjà validé en Phase 1)

    Cette phase dépend de InitialTranslationPhase.
    """

    name = "refined"
    max_tokens = 300
    overlap_ratio = 1.0  # 100% overlap pour contexte complet
    execution_mode = ExecutionMode.SEQUENTIAL
    template_name = TemplateNames.Refine_Template

    depends_on = [InitialTranslationPhase]  # Nécessite Phase 1

    checks = [
        LineCountCheck(),
        FragmentCountCheck(),
        PunctuationCheck(),
        SentenceCheck(),
    ]

    @classmethod
    def before_chunk(cls, chunk: Chunk, context: ChunkContext) -> None:
        """
        Hook avant traitement d'un chunk.

        Exporte le glossaire pour injection dans le prompt.

        Args:
            chunk: Chunk à traiter
            context: Contexte du chunk
        """
        pass

    @classmethod
    def render_prompt(cls, chunk: Chunk, context: ChunkContext) -> str:
        """
        Génère le prompt de raffinage.

        Utilise le template translate_refine avec:
        - Glossaire appris en Phase 1
        - Traduction initiale comme base

        Args:
            chunk: Chunk à raffiner
            context: Contexte du chunk

        Returns:
            Prompt formaté pour le LLM
        """
        # Récupérer traduction initiale
        initial_translation = context.store_manager.get_store("initial")

        if initial_translation is None:
            logger.warning(
                f"Traduction initiale manquante pour chunk {chunk.index}, "
                "le raffinage se fera sans base"
            )

        # Rendre le prompt avec glossaire + traduction initiale
        return context.llm.renderer.render_refine(
            chunk=chunk,
            glossary=context.glossary,
            target_language=context.target_language,
            store=initial_translation,
        )

    @classmethod
    def after_phase(cls, stats: PhaseStats, context: PhaseContext) -> None:
        """
        Hook après la fin de la phase.

        Affiche les statistiques du glossaire.

        Args:
            stats: Statistiques d'exécution
            context: Contexte global
        """
        pass
