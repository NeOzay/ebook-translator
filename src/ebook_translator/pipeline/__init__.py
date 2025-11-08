"""
Module pipeline - Système de phases modulaire pour la traduction d'ebooks.

Ce module fournit une architecture flexible pour définir et exécuter des phases
de traduction avec validation, transitions, et gestion de cache.
"""

from ebook_translator.pipeline.base import PhaseBase, ExecutionMode
from ebook_translator.pipeline.context import PhaseContext, ChunkContext, PhaseStats
from ebook_translator.pipeline.store_manager import StoreManager
from ebook_translator.pipeline.executor import PhaseExecutor
from ebook_translator.pipeline.pipeline import Pipeline

__all__ = [
    "PhaseBase",
    "ExecutionMode",
    "PhaseContext",
    "ChunkContext",
    "PhaseStats",
    "StoreManager",
    "PhaseExecutor",
    "Pipeline",
]
