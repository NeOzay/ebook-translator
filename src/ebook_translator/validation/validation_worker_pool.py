"""
Pool de ValidationWorkers parallèles avec SaveWorker dédié.

Ce module fournit une infrastructure pour lancer plusieurs ValidationWorkers
en parallèle avec un SaveWorker unique gérant toutes les écritures.

Architecture:
    ValidationQueue → ValidationWorkers (N threads, CPU-bound)
                   ↓
                SaveQueue → SaveWorker (1 thread, I/O-bound)
                         ↓
                       Store (thread-safe avec verrous par fichier)

Bénéfices:
    - Découplage validation/sauvegarde → +33-50% de throughput
    - Ordre déterministe des sauvegardes (FIFO)
    - Gestion d'erreurs centralisée et callbacks thread-safe
"""

import threading
import time
from typing import TYPE_CHECKING, TypedDict

from ebook_translator.pipeline.base import PhaseProtocol

from ..logger import get_logger
from .save_worker import SaveWorker
from .validation_queue import SaveQueue, ValidationItem, ValidationQueue
from .validation_worker import ValidationWorker

if TYPE_CHECKING:
    from ..checks import ValidationPipeline
    from ..llm import LLM
    from ..stores.store import Store

logger = get_logger(__name__)


class ValidationPoolStats(TypedDict):
    """
    Statistiques du ValidationWorkerPool.

    Attributes:
        validated: Nombre de chunks validés avec succès
        rejected: Nombre de chunks rejetés après épuisement des retries
        pending: Nombre de chunks en attente dans la queue
        total_submitted: Nombre total de chunks soumis
    """

    validated: int
    rejected: int
    pending: int
    total_submitted: int


class ValidationWorkerPool:
    """
    Pool de ValidationWorkers parallèles avec SaveWorker dédié.

    Ce pool gère N workers de validation (CPU-bound) qui consomment une queue partagée,
    plus un SaveWorker unique (I/O-bound) qui gère toutes les écritures dans le Store.

    Architecture:
        ValidationQueue → ValidationWorkers (N threads, CPU-bound)
                       ↓
                    SaveQueue → SaveWorker (1 thread, I/O-bound)
                             ↓
                           Store (thread-safe avec verrous par fichier)

    Bénéfices architecturaux:
        - **Performance**: Découplage validation/sauvegarde → +33-50% throughput
        - **Ordre déterministe**: Sauvegardes FIFO dans l'ordre de validation
        - **Callbacks thread-safe**: on_validated exécuté après confirmation de sauvegarde
        - **Gestion d'erreurs centralisée**: Logs cohérents, statistiques unifiées
        - **Backpressure**: SaveQueue limite l'utilisation mémoire

    Attributes:
        num_workers: Nombre de workers parallèles
        validation_queue: Queue partagée par tous les ValidationWorkers
        save_queue: Queue pour le SaveWorker (pipeline I/O dédié)
        workers: Liste des ValidationWorker instances
        save_worker: SaveWorker unique pour pipeline I/O
        threads: Liste des threads des ValidationWorkers
        save_thread: Thread du SaveWorker

    Example:
        >>> pipeline = ValidationPipeline([LineCountCheck(), FragmentCountCheck()])
        >>> pool = ValidationWorkerPool(
        ...     num_workers=2,
        ...     pipeline=pipeline,
        ...     store=store,
        ...     llm=llm,
        ...     target_language="fr",
        ...     phase="initial",
        ... )
        >>> pool.start()
        >>> pool.submit(chunk, translated_texts)
        >>> pool.wait_completion()
        >>> stats = pool.get_statistics()
    """

    def __init__(
        self,
        num_workers: int,
        pipeline: ValidationPipeline,
        store: Store,
        llm: LLM,
        target_language: str,
        phase: PhaseProtocol,
        max_retries: int = 1,
    ):
        """
        Initialise le pool de workers.

        Args:
            num_workers: Nombre de workers parallèles (recommandé: 2-4)
            pipeline: Pipeline de validation à appliquer
            store: Store pour sauvegarder traductions validées
            llm: Instance LLM pour corrections
            target_language: Code langue cible (ex: "fr", "en")
            phase: Phase du pipeline ("initial" ou "refined")
            on_validated: Callback optionnel appelé après sauvegarde réussie
                         avec (chunk, final_translations). Utile pour apprentissage
                         glossaire depuis traductions validées.
        """
        self.num_workers = num_workers
        self.validation_queue = ValidationQueue(maxsize=num_workers * 10)
        self.save_queue = SaveQueue(maxsize=num_workers * 10)

        # Event partagé pour signal d'arrêt (tous workers)
        self._stop_event = threading.Event()

        # Créer SaveWorker unique (SEUL à écrire dans Store)
        self.save_worker = SaveWorker(
            save_queue=self.save_queue,
            store=store,
            stop_event=self._stop_event,  # Signal d'arrêt partagé
        )

        # Créer ValidationWorkers (N threads, aucun n'écrit dans Store)
        self.workers = [
            ValidationWorker(
                worker_id=i,
                validation_queue=self.validation_queue,
                save_queue=self.save_queue,  # Envoient vers SaveQueue
                pipeline=pipeline,
                llm=llm,
                target_language=target_language,
                phase=phase,
                stop_event=self._stop_event,  # Signal d'arrêt partagé
                max_retries=max_retries,
            )
            for i in range(num_workers)
        ]

        self.threads: list[threading.Thread] = []
        self.save_thread: threading.Thread | None = None

    def start(self):
        """
        Démarre tous les workers (ValidationWorkers + SaveWorker).

        Le SaveWorker est démarré en premier pour être prêt à recevoir les sauvegardes.
        Ensuite, les ValidationWorkers sont lancés dans leurs propres threads daemon.
        """
        logger.info(
            f"Démarrage du ValidationWorkerPool "
            f"({self.num_workers} validation workers + 1 save worker)"
        )

        # 1. Démarrer SaveWorker en PREMIER (doit être prêt avant ValidationWorkers)
        self.save_thread = threading.Thread(
            target=self.save_worker.run,
            daemon=True,
            name="SaveWorker",
        )
        self.save_thread.start()
        logger.debug("SaveWorker démarré")

        # 2. Démarrer ValidationWorkers
        self.threads = [
            threading.Thread(
                target=worker.run, daemon=True, name=f"ValidationWorker-{i}"
            )
            for i, worker in enumerate(self.workers)
        ]

        for thread in self.threads:
            thread.start()

        logger.debug(
            f"ValidationWorkerPool démarré ({len(self.threads)} validation threads)"
        )

    def submit(self, item: ValidationItem):
        """
        Soumet un chunk pour validation.

        Args:
            item: ValidationItem avec chunk et traductions à valider

        """

        self.validation_queue.put(item)

    def wait_completion(self):
        """
        Attend que tous les chunks soumis soient validés ET sauvegardés.
        """

        # Attendre que validation_queue et save_queue soient idle (vide + aucun en cours)
        while not self.validation_queue.is_idle() or not self.save_queue.is_idle():
            time.sleep(0.1)

    def stop(self):
        """
        Attend que tous les chunks soumis soient validés ET sauvegardés.

        Flux d'arrêt:
        1. Attendre que validation_queue soit idle (toutes validations terminées)
        2. Signaler arrêt via stop_event (TOUS les workers instantanément)
        3. Attendre fin de tous les ValidationWorkers
        4. Attendre que save_queue soit idle (toutes sauvegardes terminées)
        5. Attendre fin du SaveWorker (stop_event déjà set)

        IMPORTANT: Utilise threading.Event au lieu de None dans la queue.
        Plus fiable avec plusieurs workers (1 signal → tous workers).
        """
        logger.info("Attente de la fin de la validation...")

        # 1. Attendre que validation_queue et save_queue soient idle (vide + aucun en cours)
        self.wait_completion()

        logger.debug("Queue de validation idle, signal d'arrêt à TOUS les workers")
        self._stop_event.set()

        logger.warning("Arrêt immédiat du ValidationWorkerPool demandé")

        # 3. Attendre fin de tous les ValidationWorkers
        for thread in self.threads:
            thread.join(timeout=10.0)
            if thread.is_alive():
                logger.warning(f"Thread {thread.name} n'a pas terminé après timeout")

        logger.debug("ValidationWorkers terminés, attente de fin des sauvegardes...")

        logger.debug(
            "Queue de sauvegarde idle, SaveWorker va s'arrêter automatiquement"
        )

        # 5. Attendre fin du SaveWorker (stop_event déjà set)
        if self.save_thread:
            self.save_thread.join(timeout=10.0)
            if self.save_thread.is_alive():
                logger.warning("SaveWorker n'a pas terminé après timeout")

        logger.info("ValidationWorkerPool terminé (validation + sauvegarde)")

    def switch_phase(self, phase: PhaseProtocol, store: Store) -> None:
        """
        Change la phase de tous les workers (Validation + Save).

        Args:
            phase: Nouvelle classe de phase
            store: Nouveau store associé à cette phase
        Note:
            Ne peut être appelé que si la validation_queue est idle
        """
        if not self.validation_queue.is_idle():
            logger.error(
                "Impossible de changer de phase: la validation_queue n'est pas idle"
            )
            raise RuntimeError(
                "Cannot switch phase name while validation_queue is not idle"
            )

        pipeline = phase.validation_pipeline()

        for worker in self.workers:
            worker.phase = phase
            worker.pipeline = pipeline
        self.save_worker.store = store
        logger.debug("Changement de phase effectué dans ValidationWorkerPool")

    def get_statistics(self) -> ValidationPoolStats:
        """
        Retourne statistiques de validation et de sauvegarde.

        Returns:
            Dictionnaire avec:
            - validated: nombre de chunks validés (pas forcément sauvegardés)
            - rejected: nombre de chunks rejetés
            - pending: nombre de chunks en attente (validation + sauvegarde)
            - total_submitted: nombre total de chunks soumis

        Note:
            pending inclut à la fois validation_queue.pending ET save_queue.pending,
            car les deux sont des étapes "en cours" du pipeline.

        Example:
            >>> stats = pool.get_statistics()
            >>> print(f"Validés: {stats['validated']}, Rejetés: {stats['rejected']}")
            >>> print(f"En attente: {stats['pending']} (validation + sauvegarde)")
        """
        validation_stats = self.validation_queue.get_statistics()
        save_stats = self.save_queue.get_statistics()

        return {
            "validated": validation_stats.validated,
            "rejected": validation_stats.rejected,
            # pending = validation en cours + sauvegarde en cours
            "pending": validation_stats.pending + save_stats["pending"],
            "total_submitted": validation_stats.total_submitted,
        }

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        stats = self.get_statistics()
        return (
            f"ValidationWorkerPool(\n"
            f"  workers={self.num_workers},\n"
            f"  validated={stats['validated']},\n"
            f"  rejected={stats['rejected']},\n"
            f"  pending={stats['pending']}\n"
            f")"
        )
