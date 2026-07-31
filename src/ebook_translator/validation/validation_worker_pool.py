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

Le type de worker est choisi **par phase** (`_worker_class`) : sans
`content_checks`, la donnée n'est pas un mapping line-indexed et part vers
`SchemaOnlyValidationWorker`, qui la relaie sans y toucher.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, TypedDict

from ..logger import get_logger
from .save_worker import SaveWorker
from .schema_only_worker import SchemaOnlyValidationWorker
from .unified_worker import UnifiedValidationWorker
from .validation_queue import SaveQueue, ValidationItem, ValidationQueue
from .worker_base import ValidationWorker

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
        # Événement distinct des workers de validation : un changement de
        # phase peut devoir les recycler (classe de worker différente) sans
        # interrompre le `SaveWorker`, qui draine encore la phase précédente.
        self._validation_stop_event = threading.Event()

        self.save_worker = SaveWorker(
            save_queue=self.save_queue,
            stop_event=self._stop_event,
        )

        self._worker_class: type[ValidationWorker[Any]] = self._select_worker_class(
            phase
        )
        self.workers: list[ValidationWorker[Any]] = self._build_workers(phase)

        self.threads: list[threading.Thread] = []
        self.save_thread: threading.Thread | None = None
        self._started = False

    @staticmethod
    def _select_worker_class(phase: PhaseProtocol) -> type[ValidationWorker[Any]]:
        """Choisit le worker adapté à la phase.

        C'est ici, et pas dans le worker, que se décide la forme de la
        donnée : `UnifiedValidationWorker` suppose un mapping line-indexed,
        que les phases à schéma seul (Phase 0, glossaire) ne fournissent pas.

        Args:
            phase: Phase dont les `content_checks` arbitrent le choix.

        Returns:
            La classe de worker à instancier pour cette phase.
        """
        return (
            UnifiedValidationWorker
            if phase.content_checks
            else SchemaOnlyValidationWorker
        )

    def _build_workers(self, phase: PhaseProtocol) -> list[ValidationWorker[Any]]:
        """Instancie `num_workers` workers du type requis par `phase`.

        Le worker lit `llm` et `target_language` sur `CommunContext`, gelé
        par le `Pipeline` avant la construction du pool.

        Args:
            phase: Phase courante.

        Returns:
            Les workers, non démarrés.
        """
        # Chaque génération de workers reçoit son propre événement d'arrêt.
        # Un worker qui n'aurait pas rendu la main dans le délai de `join`
        # garde ainsi un signal armé et finit par sortir, au lieu d'être
        # réveillé par la remise à zéro de la génération suivante.
        self._validation_stop_event = threading.Event()
        return [
            self._worker_class(
                validation_queue=self.validation_queue,
                save_queue=self.save_queue,
                phase=phase,
                stop_event=self._validation_stop_event,
            )
            for _ in range(self.num_workers)
        ]

    def _start_validation_threads(self) -> None:
        """Démarre un thread par worker de validation."""

        self.threads = [
            threading.Thread(
                target=worker.run,
                daemon=True,
                name=f"{type(worker).__name__}-{i}",
            )
            for i, worker in enumerate(self.workers)
        ]
        for thread in self.threads:
            thread.start()

    def _stop_validation_threads(self) -> None:
        """Signale l'arrêt des workers de validation et attend leurs threads."""

        self._validation_stop_event.set()
        for thread in self.threads:
            thread.join(timeout=10.0)
            if thread.is_alive():
                logger.warning(f"Thread {thread.name} non terminé après timeout")
        self.threads = []

    def start(self) -> None:
        logger.info(
            f"Démarrage ValidationWorkerPool "
            f"({self.num_workers} × {self._worker_class.__name__} "
            f"+ 1 save worker)"
        )

        self.save_thread = threading.Thread(
            target=self.save_worker.run,
            daemon=True,
            name="SaveWorker",
        )
        self.save_thread.start()

        self._start_validation_threads()
        self._started = True

    def submit(self, item: ValidationItem) -> None:
        self.validation_queue.put(item)

    def wait_completion(self) -> None:
        while not self.validation_queue.is_idle() or not self.save_queue.is_idle():
            time.sleep(0.1)

    def stop(self) -> None:
        logger.info("Attente fin de validation...")
        self.wait_completion()
        self._stop_validation_threads()
        self._started = False
        self._stop_event.set()
        if self.save_thread:
            self.save_thread.join(timeout=10.0)
            if self.save_thread.is_alive():
                logger.warning("SaveWorker non terminé après timeout")
        logger.info("ValidationWorkerPool terminé")

    def switch_phase(self, phase: PhaseProtocol) -> None:
        """Change la phase courante de tous les workers de validation.

        Si la nouvelle phase demande un autre type de worker (passage d'une
        phase à `content_checks` à une phase validée par schéma seul, ou
        l'inverse), les workers sont recyclés plutôt que reconfigurés.

        Le `SaveWorker` n'est pas concerné — chaque `SaveItem` porte
        son propre persister + byte_store.

        Args:
            phase: Phase qui démarre.

        Raises:
            RuntimeError: Si la `validation_queue` n'est pas idle.
        """

        if not self.validation_queue.is_idle():
            logger.error("Impossible de changer de phase : validation_queue non idle")
            raise RuntimeError("Cannot switch phase while validation_queue is not idle")

        worker_class = self._select_worker_class(phase)
        if worker_class is self._worker_class:
            for worker in self.workers:
                worker.phase = phase
            logger.debug("Switch phase effectué dans ValidationWorkerPool")
            return

        if self._started:
            self._stop_validation_threads()
        self._worker_class = worker_class
        self.workers = self._build_workers(phase)
        if self._started:
            self._start_validation_threads()
        logger.debug(
            f"Switch phase effectué dans ValidationWorkerPool "
            f"(workers recyclés en {worker_class.__name__})"
        )

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
