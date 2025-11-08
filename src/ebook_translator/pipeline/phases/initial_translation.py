"""
Phase 1: Traduction initiale avec gros blocs.
"""

from ebook_translator.pipeline.base import PhaseBase, ExecutionMode
from ebook_translator.pipeline.context import ChunkContext
from ebook_translator.segmentation.segmentator import Chunk
from ebook_translator.config import TemplateNames
from ebook_translator.checks import (
    LineCountCheck,
    FragmentCountCheck,
    PunctuationCheck,
    SentenceCheck,
)


class InitialTranslationPhase(PhaseBase):
    """
    Phase 1: Traduction initiale (gros blocs, parallèle).

    Configuration:
    - max_tokens: 1500 (gros blocs pour contexte large)
    - overlap_ratio: 0.15 (15% de chevauchement)
    - execution_mode: PARALLEL (traduction parallèle pour performance)
    - template: translate_base (traduction standard sans glossaire)

    Validation:
    - LineCountCheck: Toutes les lignes traduites
    - FragmentCountCheck: Nombre correct de séparateurs </>
    - PunctuationCheck: Paires de guillemets correctes
    - SentenceCheck: Pas de phrases tronquées

    Cette phase ne dépend d'aucune autre phase.
    """

    name = "initial"
    max_tokens = 1500
    overlap_ratio = 0.15
    execution_mode = ExecutionMode.PARALLEL
    template_name = TemplateNames.First_Pass_Template

    depends_on = []  # Première phase, aucune dépendance

    checks = [
        LineCountCheck(),
        FragmentCountCheck(),
        PunctuationCheck(),
        SentenceCheck(),
    ]

    @classmethod
    def render_prompt(cls, chunk: Chunk, context: ChunkContext) -> str:
        """
        Génère le prompt de traduction initiale.

        Utilise le template translate_base sans glossaire.

        Args:
            chunk: Chunk à traduire
            context: Contexte du chunk

        Returns:
            Prompt formaté pour le LLM
        """
        return context.llm.renderer.render_translate(context.target_language)
