"""
Phases concrètes de traduction.
"""

from ebook_translator.pipeline.phases.initial_translation import InitialTranslationPhase
from ebook_translator.pipeline.phases.refinement import RefinementPhase

__all__ = [
    "InitialTranslationPhase",
    "RefinementPhase",
]
