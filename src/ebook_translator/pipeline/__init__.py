"""
Module pipeline - Système de phases modulaire pour la traduction d'ebooks.

Ce module fournit une architecture flexible pour définir et exécuter des phases
de traduction avec validation, transitions, et gestion de cache.
"""

from .base import ExecutionMode, PhaseBase, PhaseName
from .context import ChunkContext, PhaseContext, PhaseStats
from .executor import PhaseExecutor
from .pipeline import Pipeline
from .store_manager import StoreManager

__all__ = [
    "PhaseBase",
    "ExecutionMode",
    "PhaseName",
    "PhaseContext",
    "ChunkContext",
    "PhaseStats",
    "StoreManager",
    "PhaseExecutor",
    "Pipeline",
]
