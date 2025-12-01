"""
Phases concrètes de traduction.
"""

from .dummy_phase import DummyPhase
from .initial_translation import InitialTranslationPhase
from .literary_analysis import LiteraryAnalysisPhase
from .refinement import RefinementPhase

__all__ = [
    "InitialTranslationPhase",
    "RefinementPhase",
    "LiteraryAnalysisPhase",
    "DummyPhase",
]
