"""
Phase 1: Traduction initiale avec gros blocs.
"""

from dataclasses import dataclass, field

from ebook_translator.checks import (
    FragmentCountCheck,
    LineCountCheck,
    PunctuationCheck,
    SentenceCheck,
)
from ebook_translator.pipeline.base import ExecutionMode, PhaseBase, PhaseName
from ebook_translator.pipeline.context import ChunkContext
from ebook_translator.segmentation.segmentator import Chunk


@dataclass
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

    name = PhaseName.INITIAL
    max_tokens: int = field(default=1500)
    overlap_ratio: float = field(default=0.15)
    execution_mode = ExecutionMode.PARALLEL

    depends_on = []  # Première phase, aucune dépendance

    checks = [
        LineCountCheck(),
        FragmentCountCheck(),
        PunctuationCheck(),
        SentenceCheck(),
    ]

    def render_prompt(self, chunk: Chunk, context: ChunkContext) -> str:
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
