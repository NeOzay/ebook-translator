"""
Module d'analyse littéraire (Phase 0).

Composants :
- ContexteTraduction : Schéma JSON simplifié pour traduction
- AnalysisValidator : Validation contextes de traduction
- AnalysisExporter : Export analyses en Markdown formaté

Note: Le module utilise désormais le format ContexteTraduction simplifié
qui réduit de ~67% les tokens LLM par rapport à ChapterAnalysis.

LiteraryAnalysisPhase se trouve dans pipeline.phases.literary_analysis.
"""

# from template.types import LLMTermeGlossaire

from typing import TYPE_CHECKING

from .analysis_validator import AnalysisValidator
from .translation_context import ContexteTraduction

if TYPE_CHECKING:
    from .translation_context import AnalyseLitteraire

__all__ = [
    "ContexteTraduction",
    "AnalyseLitteraire",
    # "LLMTermeGlossaire",
    "AnalysisValidator",
]
