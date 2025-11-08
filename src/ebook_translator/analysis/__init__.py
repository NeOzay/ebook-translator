"""
Module d'analyse littéraire (Phase 0).

Composants :
- LiteraryAnalysisPhase : Phase d'analyse pré-traduction
- ChapterAnalysis : Schéma JSON TypedDict
- AnalysisValidator : Validation analyses
- BlockSplitter : Découpage chapitres en blocs de ~4000 tokens
- AnalysisBlock : Bloc d'analyse individuel
- GlossaryPopulator : Population automatique glossaire depuis analyses
"""

from .schema import ChapterAnalysis
from .validator import AnalysisValidator
from .block_splitter import BlockSplitter, AnalysisBlock
from .literary_analysis_phase import LiteraryAnalysisPhase
from .glossary_populator import GlossaryPopulator

__all__ = [
    "ChapterAnalysis",
    "AnalysisValidator",
    "BlockSplitter",
    "AnalysisBlock",
    "LiteraryAnalysisPhase",
    "GlossaryPopulator",
]
