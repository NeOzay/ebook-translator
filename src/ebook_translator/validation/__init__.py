"""
Système de validation asynchrone avec workers dédiés.

Ce module fournit une infrastructure de validation parallèle qui valide
et corrige les traductions avant sauvegarde dans le Store.

Architecture:
    ValidationQueue → ValidationWorkers (N threads) → SaveQueue → SaveWorker (1 thread) → Store

Le SaveWorker est le SEUL thread autorisé à écrire dans le Store, éliminant
ainsi complètement les conflits d'écriture (WinError 32 sur Windows).
"""

from .validation_queue import ValidationQueue, SaveQueue, SaveItem, ValidationItem
from .validation_worker import ValidationWorker
from .validation_worker_pool import ValidationWorkerPool
from .save_worker import SaveWorker

__all__ = [
    "ValidationQueue",
    "ValidationWorker",
    "ValidationWorkerPool",
    "SaveQueue",
    "SaveItem",
    "ValidationItem",
    "SaveWorker",
]
