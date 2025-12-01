"""
Système de validation et correction des traductions.

Ce module fournit un pipeline composable de checks pour valider
et corriger automatiquement les traductions avant sauvegarde.
"""

from .check_tests.base import (
    Check,
    CheckResult,
    ErrorData,
    FilteredLine,
    FragmentCountErrorData,
    FragmentErrorDetail,
    LineCountErrorData,
    ValidationContext,
)
from .check_tests.fragment_count_check import FragmentCountCheck
from .check_tests.line_count_check import LineCountCheck
from .check_tests.punctuation_check import PunctuationCheck
from .check_tests.sentence_check import SentenceCheck
from .check_tests.validate_analysis import AnalysisChecks
from .pipeline import ValidationPipeline

__all__ = [
    "Check",
    "CheckResult",
    "ValidationContext",
    "ValidationPipeline",
    "LineCountCheck",
    "FragmentCountCheck",
    "PunctuationCheck",
    "SentenceCheck",
    "AnalysisChecks",
    # TypedDicts pour error_data
    "ErrorData",
    "LineCountErrorData",
    "FragmentCountErrorData",
    "FragmentErrorDetail",
    "FilteredLine",
]
