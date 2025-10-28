"""
Système de validation et correction des traductions.

Ce module fournit un pipeline composable de checks pour valider
et corriger automatiquement les traductions avant sauvegarde.
"""

from .base import (
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
from .line_count_check import LineCountCheck
from .fragment_count_check import FragmentCountCheck
from .punctuation_check import PunctuationCheck, PunctuationErrorData, PunctuationErrorDetail

__all__ = [
    "Check",
    "CheckResult",
    "ValidationContext",
    "ValidationPipeline",
    "LineCountCheck",
    "FragmentCountCheck",
    "PunctuationCheck",
    # TypedDicts pour error_data
    "ErrorData",
    "LineCountErrorData",
    "FragmentCountErrorData",
    "FragmentErrorDetail",
    "PunctuationErrorData",
    "PunctuationErrorDetail",
    "FilteredLine",
]
