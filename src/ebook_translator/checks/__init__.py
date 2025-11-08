"""
Système de validation et correction des traductions.

Ce module fournit un pipeline composable de checks pour valider
et corriger automatiquement les traductions avant sauvegarde.
"""

from .check_tests.base import (
    Check,
    CheckResult,
    ValidationContext,
    ErrorData,
    LineCountErrorData,
    FragmentCountErrorData,
    FragmentErrorDetail,
    FilteredLine,
)
from .pipeline import ValidationPipeline
from .check_tests.line_count_check import LineCountCheck
from .check_tests.fragment_count_check import FragmentCountCheck
from .check_tests.punctuation_check import (
    PunctuationCheck,
    PunctuationErrorData,
    PunctuationErrorDetail,
)
from .check_tests.sentence_check import SentenceCheck

__all__ = [
    "Check",
    "CheckResult",
    "ValidationContext",
    "ValidationPipeline",
    "LineCountCheck",
    "FragmentCountCheck",
    "PunctuationCheck",
    "SentenceCheck",
    # TypedDicts pour error_data
    "ErrorData",
    "LineCountErrorData",
    "FragmentCountErrorData",
    "FragmentErrorDetail",
    "PunctuationErrorData",
    "PunctuationErrorDetail",
    "FilteredLine",
]
