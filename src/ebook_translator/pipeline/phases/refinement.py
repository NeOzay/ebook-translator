"""
Phase 2: Raffinage avec glossaire et petits blocs.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from ebook_translator.checks import (
    FragmentCountCheck,
    LineCountCheck,
    PunctuationCheck,
    SentenceCheck,
)
from ebook_translator.logger import get_logger
from ebook_translator.pipeline.base import ExecutionMode, PhaseBase, PhaseName
from ebook_translator.pipeline.context import ChunkContext
from ebook_translator.pipeline.phases.initial_translation import InitialTranslationPhase
from ebook_translator.segmentation.chapter_chunk import ChapterPartChunk
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

    checks = (
        LineCountCheck(),
        FragmentCountCheck(),
        PunctuationCheck(),
        SentenceCheck(),
    )

    def _get_literary_context(
        self, chunk: Chunk, context: ChunkContext
    ) -> dict[str, Any] | None:
        """
        Récupère l'analyse littéraire du chapitre depuis Phase 0 si disponible.

        Args:
            chunk: Chunk à traduire
            context: Contexte du chunk

        Returns:
            Analyse littéraire (AnalyseLitteraire) ou None si non disponible
        """
        # Vérifier si le chunk est lié à un chapitre
        if not isinstance(chunk, ChapterPartChunk):
            return None

        try:
            # Récupérer le store d'analyse littéraire
            literary_store = context.store_manager.get_store("literary_analysis")
            chapter_name = chunk.chapter.name

            # ChapterChunk a toujours index=0, hash basé sur contenu
            keyname = f"0_{chunk.chapter.calculate_chunk_hash()[:8]}"
            cached_json = literary_store.get(chapter_name, keyname)

            if cached_json is None:
                logger.debug(
                    f"No literary analysis found for chapter '{chapter_name}' "
                    f"(key: {keyname})"
                )
                return None

            # Parser le JSON et extraire la section 'analyse'
            analysis = json.loads(cached_json)
            return analysis.get("analyse")

        except (json.JSONDecodeError, KeyError, AttributeError) as e:
            logger.warning(
                f"Failed to load literary analysis for chapter '{chunk.chapter.name}': {e}"
            )
            return None

    def render_prompt(self, chunk: Chunk, context: ChunkContext) -> str:
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
        literary_context = self._get_literary_context(chunk, context)

        # Rendre le prompt avec glossaire + traduction initiale + analyse littéraire
        return context.llm.renderer.render_refine(
            chunk=chunk,
            glossary=context.glossary,
            target_language=context.target_language,
            store=initial_translation,
            literary_context=literary_context,
        )
