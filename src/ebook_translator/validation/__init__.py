"""Système de validation asynchrone avec workers dédiés.

Architecture (Bloc B Step 4c) :

    ValidationQueue → UnifiedValidationWorker (N threads, CPU-bound)
                   ↓
                SaveQueue → SaveWorker (1 thread, I/O-bound)
                         ↓
                       ByteStore (via SaveItem self-contained)

Les symboles sont exposés en **import paresseux** (PEP 562). Les workers
dépendent de `checks` et `pipeline`, qui dépendent eux-mêmes des modules bas
de `validation` (`diagnostics`, `failure`). Un import eager ici refermerait
ce cycle dès qu'un module bas est importé.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .save_worker import SaveWorker
    from .unified_worker import UnifiedValidationWorker
    from .validation_queue import SaveItem, SaveQueue, ValidationItem, ValidationQueue
    from .validation_worker_pool import ValidationWorkerPool

_LAZY: dict[str, str] = {
    "SaveWorker": ".save_worker",
    "UnifiedValidationWorker": ".unified_worker",
    "SaveItem": ".validation_queue",
    "SaveQueue": ".validation_queue",
    "ValidationItem": ".validation_queue",
    "ValidationQueue": ".validation_queue",
    "ValidationWorkerPool": ".validation_worker_pool",
}

__all__ = [
    "SaveItem",
    "SaveQueue",
    "SaveWorker",
    "UnifiedValidationWorker",
    "ValidationItem",
    "ValidationQueue",
    "ValidationWorkerPool",
]


def __getattr__(name: str) -> Any:
    """Résout un symbole du package à la première utilisation (PEP 562).

    Args:
        name: Nom du symbole demandé.

    Returns:
        L'objet importé depuis son sous-module.

    Raises:
        AttributeError: Si `name` n'est pas exposé par le package.
    """
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from importlib import import_module

    return getattr(import_module(module_name, __name__), name)
