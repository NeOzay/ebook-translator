"""
Phases concrètes de traduction.
"""

from .dummy_phase import DummyPhase
from .glossary import GlossaryPhase
from .initial_translation import InitialTranslationPhase
from .literary_analysis import LiteraryAnalysisPhase
from .refinement import RefinementPhase

__all__ = [
    "InitialTranslationPhase",
    "GlossaryPhase",
    "RefinementPhase",
    "LiteraryAnalysisPhase",
    "DummyPhase",
]
