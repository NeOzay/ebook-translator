"""
Phase 2: Raffinage avec glossaire et petits blocs.
"""

from dataclasses import dataclass, field
from typing import Any, override

from ebook_translator.checks import (
    Check,
    FragmentCountCheck,
    LineCountCheck,
    PunctuationCheck,
    SentenceCheck,
)
from ebook_translator.logger import get_logger
from ebook_translator.pipeline.base import ExecutionMode, PhaseBase, PhaseName
from ebook_translator.pipeline.context import ChunkContext
from ebook_translator.pipeline.phases.initial_translation import InitialTranslationPhase
from ebook_translator.segmentation.segmentator import Chunk

logger = get_logger(__name__)


@dataclass
class RefinementPhase(PhaseBase[Chunk]):
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

    name = PhaseName.REFINEMENT
    chunk_type = Chunk
    max_tokens: int = field(default=300)
    overlap_ratio: float = field(default=1.0)  # 100% overlap pour contexte complet
    execution_mode = ExecutionMode.SEQUENTIAL

    depends_on = (InitialTranslationPhase,)  # Nécessite Phase 1

    checks: tuple[Check[Any], ...] = field(
        default=(
            LineCountCheck(),
            FragmentCountCheck(),
            PunctuationCheck(),
            SentenceCheck(),
        ),
        init=False,
    )

    @override
    def render_prompt(self, chunk: Chunk, context: ChunkContext) -> tuple[str, str]:
        """
        Génère le prompt de raffinage.

        Utilise le template translate_refine avec:
        - Glossaire appris en Phase 1
        - Traduction initiale comme base
        - Analyse littéraire du chapitre (si Phase 0 exécutée)

        Args:
            chunk: Chunk à raffiner
            context: Contexte du chunk

        Returns:
            Prompt formaté pour le LLM
        """
        # Récupérer traduction initiale
        initial_translation = context.store_manager.get_store("initial")

        # Récupérer analyse littéraire si disponible
        literary_context = self.get_literary_context(chunk, context)

        # Rendre le prompt avec glossaire + traduction initiale + analyse littéraire
        return context.llm.renderer.render_refine(
            chunk=chunk,
            glossary=context.glossary,
            target_language=context.target_language,
            store=initial_translation,
            literary_context=literary_context,
        )
