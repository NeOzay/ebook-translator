"""
Phase 1: Traduction initiale avec gros blocs.
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
from ebook_translator.segmentation.segmentator import Chunk

logger = get_logger(__name__)


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
    chunk_type = Chunk
    max_tokens: int = field(default=1500)
    overlap_ratio: float = field(default=0.15)
    execution_mode = ExecutionMode.PARALLEL

    depends_on = ()  # Première phase, aucune dépendance

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

        if not self.context.get_previous_stats(PhaseName.LITERARY_ANALYSIS):
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
        Génère le prompt de traduction initiale.

        Utilise le template translate_base sans glossaire.
        Si Phase 0 a été exécutée, inclut l'analyse littéraire du chapitre.

        Args:
            chunk: Chunk à traduire
            context: Contexte du chunk

        Returns:
            Prompt formaté pour le LLM
        """
        literary_context = self._get_literary_context(chunk, context)
        return context.llm.renderer.render_translate(
            context.target_language, literary_context=literary_context
        )
