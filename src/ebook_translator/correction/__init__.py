"""
Module pour la correction automatique des erreurs de traduction.

Ce module gère la correction automatique des erreurs de segmentation
via retry LLM avec prompts renforcés.
"""

from .retry_engine import RetryEngine, CorrectionResult

__all__ = [
    "RetryEngine",
    "CorrectionResult",
]
