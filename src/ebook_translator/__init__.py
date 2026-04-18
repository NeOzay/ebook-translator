# Classes LLM et traduction
# Classes HTML
from .htmlpage import BilingualFormat
from .llm import LLM
from .pipeline import Pipeline
from .pipeline.builder import LLMBuilder, PhasesBuilder, PipelineBuilder
from .pipeline.phases import (
    InitialTranslationPhase,
    LiteraryAnalysisPhase,
    RefinementPhase,
)
from .translation.language import Language

# Version du package
__version__ = "0.1.0"

# Exports publics
__all__ = [
    # Version
    "__version__",
    # Classes principales
    "LLM",
    # Classes HTML
    "BilingualFormat",
    # Constantes
    "Language",
    # Pipeline
    "Pipeline",
    # Builder
    "PipelineBuilder",
    "LLMBuilder",
    "PhasesBuilder",
    # Phases
    "LiteraryAnalysisPhase",
    "InitialTranslationPhase",
    "RefinementPhase",
]
