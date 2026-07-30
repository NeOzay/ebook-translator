"""Pool de `UnifiedValidationWorker` parallèles + `SaveWorker` dédié.

Architecture (Bloc B Step 4c) :

    ValidationQueue → UnifiedValidationWorkers (N threads, CPU-bound)
                   ↓
                SaveQueue → SaveWorker (1 thread, I/O-bound)
                         ↓
                       ByteStore (via SaveItem self-contained)

Chaque `UnifiedValidationWorker` route via `RETRY_REGISTRY` et les
métadonnées des `ContentCheck`. Le pool ne porte ni `pipeline` ni
`max_retries` — la politique de retry (`retry_strategy`, `max_attempts`)
est déclarée par chaque check.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, TypedDict

from ..logger import get_logger
from .save_worker import SaveWorker
from .unified_worker import UnifiedValidationWorker
from .validation_queue import SaveQueue, ValidationItem, ValidationQueue

if TYPE_CHECKING:
    from ebook_translator.pipeline.base import PhaseProtocol


logger = get_logger(__name__)


class ValidationPoolStats(TypedDict):
    validated: int
    rejected: int
    pending: int
    total_submitted: int


class ValidationWorkerPool:
    """Pool de workers de validation avec `SaveWorker` dédié.

    Attributes:
        num_workers: Nombre de workers parallèles (recommandé 2-4).
        validation_queue: Queue partagée entrée → workers.
        save_queue: Queue workers → SaveWorker.
        workers: Liste des `UnifiedValidationWorker`.
        save_worker: SaveWorker unique.
    """

    def __init__(
        self,
        num_workers: int,
        phase: PhaseProtocol,
    ) -> None:
        self.num_workers = num_workers
        self.validation_queue: ValidationQueue = ValidationQueue(
            maxsize=num_workers * 10
        )
        self.save_queue: SaveQueue = SaveQueue(maxsize=num_workers * 10)
        self._stop_event = threading.Event()

        self.save_worker = SaveWorker(
            save_queue=self.save_queue,
            stop_event=self._stop_event,
        )

        # Le worker lit `llm` et `target_language` sur `CommunContext`, gelé
        # par le `Pipeline` avant la construction du pool.
        self.workers: list[UnifiedValidationWorker] = [
            UnifiedValidationWorker(
                validation_queue=self.validation_queue,
                save_queue=self.save_queue,
                phase=phase,
                stop_event=self._stop_event,
            )
            for _ in range(num_workers)
        ]

        self.threads: list[threading.Thread] = []
        self.save_thread: threading.Thread | None = None

    def start(self) -> None:
        logger.info(
            f"Démarrage ValidationWorkerPool "
            f"({self.num_workers} unified workers + 1 save worker)"
        )

        self.save_thread = threading.Thread(
            target=self.save_worker.run,
            daemon=True,
            name="SaveWorker",
        )
        self.save_thread.start()

        self.threads = [
            threading.Thread(target=worker.run, daemon=True, name=f"UnifiedWorker-{i}")
            for i, worker in enumerate(self.workers)
        ]
        for thread in self.threads:
            thread.start()

    def submit(self, item: ValidationItem) -> None:
        self.validation_queue.put(item)

    def wait_completion(self) -> None:
        while not self.validation_queue.is_idle() or not self.save_queue.is_idle():
            time.sleep(0.1)

    def stop(self) -> None:
        logger.info("Attente fin de validation...")
        self.wait_completion()
        self._stop_event.set()
        for thread in self.threads:
            thread.join(timeout=10.0)
            if thread.is_alive():
                logger.warning(f"Thread {thread.name} non terminé après timeout")
        if self.save_thread:
            self.save_thread.join(timeout=10.0)
            if self.save_thread.is_alive():
                logger.warning("SaveWorker non terminé après timeout")
        logger.info("ValidationWorkerPool terminé")

    def switch_phase(self, phase: PhaseProtocol) -> None:
        """Change la phase courante de tous les workers de validation.

        Le `SaveWorker` n'est pas concerné — chaque `SaveItem` porte
        son propre persister + byte_store.
        """

        if not self.validation_queue.is_idle():
            logger.error("Impossible de changer de phase : validation_queue non idle")
            raise RuntimeError("Cannot switch phase while validation_queue is not idle")
        for worker in self.workers:
            worker.phase = phase
        logger.debug("Switch phase effectué dans ValidationWorkerPool")

    def get_statistics(self) -> ValidationPoolStats:
        validation_stats = self.validation_queue.get_statistics()
        save_stats = self.save_queue.get_statistics()
        return {
            "validated": validation_stats.validated,
            "rejected": validation_stats.rejected,
            "pending": validation_stats.pending + save_stats["pending"],
            "total_submitted": validation_stats.total_submitted,
        }

    def __repr__(self) -> str:
        stats = self.get_statistics()
        return (
            f"ValidationWorkerPool(workers={self.num_workers}, "
            f"validated={stats['validated']}, rejected={stats['rejected']}, "
            f"pending={stats['pending']})"
        )
