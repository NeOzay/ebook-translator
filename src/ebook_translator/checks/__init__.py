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
)
from .pipeline import ValidationPipeline
from .line_count_check import LineCountCheck
from .fragment_count_check import FragmentCountCheck

__all__ = [
    "Check",
    "CheckResult",
    "ValidationContext",
    "ValidationPipeline",
    "LineCountCheck",
    "FragmentCountCheck",
    # TypedDicts pour error_data
    "ErrorData",
    "LineCountErrorData",
    "FragmentCountErrorData",
    "FragmentErrorDetail",
]
