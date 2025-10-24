"""
Pool de ValidationWorkers parallèles.

Ce module fournit une infrastructure pour lancer plusieurs ValidationWorkers
en parallèle et coordonner leur arrêt gracieux.
"""

import threading
import time
from typing import TYPE_CHECKING, Literal, Callable, TypedDict

from ..logger import get_logger
from .validation_queue import ValidationQueue, ValidationItem, SaveQueue
from .validation_worker import ValidationWorker
from .save_worker import SaveWorker

if TYPE_CHECKING:
    from ..checks import ValidationPipeline
    from ..llm import LLM
    from ..segment import Chunk
    from ..store import Store

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

    Ce pool gère N workers de validation qui consomment une queue partagée,
    plus un SaveWorker unique qui s'occupe de toutes les écritures dans le Store.

    Architecture:
        ValidationQueue → ValidationWorkers (N threads) → SaveQueue → SaveWorker (1 thread) → Store

    Attributes:
        num_workers: Nombre de workers parallèles
        validation_queue: Queue partagée par tous les ValidationWorkers
        save_queue: Queue pour le SaveWorker (écriture unique)
        workers: Liste des ValidationWorker instances
        save_worker: SaveWorker unique pour écriture thread-safe
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
        pipeline: "ValidationPipeline",
        store: "Store",
        llm: "LLM",
        target_language: str,
        phase: Literal["initial", "refined"],
        on_validated: Callable[["Chunk", dict[int, str]], None] | None = None,
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

        # Créer SaveWorker unique (SEUL à écrire dans Store)
        self.save_worker = SaveWorker(
            save_queue=self.save_queue,
            store=store,
            on_validated=on_validated,  # Callback géré par SaveWorker
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
            threading.Thread(target=worker.run, daemon=True, name=f"ValidationWorker-{i}")
            for i, worker in enumerate(self.workers)
        ]

        for thread in self.threads:
            thread.start()

        logger.debug(f"ValidationWorkerPool démarré ({len(self.threads)} validation threads)")

    def submit(self, chunk: "Chunk", translated_texts: dict[int, str]):
        """
        Soumet un chunk pour validation.

        Args:
            chunk: Chunk avec textes originaux
            translated_texts: Traductions à valider {line_index: translated_text}

        Example:
            >>> pool.submit(chunk, {0: "Bonjour", 1: "Monde"})
        """
        item = ValidationItem(chunk=chunk, translated_texts=translated_texts)
        self.validation_queue.put(item)

    def wait_completion(self):
        """
        Attend que tous les chunks soumis soient validés ET sauvegardés.

        Flux d'arrêt:
        1. Attendre que validation_queue soit vide (toutes validations terminées)
        2. Arrêter ValidationWorkers
        3. Attendre que save_queue soit vide (toutes sauvegardes terminées)
        4. Arrêter SaveWorker
        5. Attendre terminaison de tous les threads

        IMPORTANT: Ne pas oublier d'attendre save_queue, sinon certaines
        sauvegardes peuvent être perdues!
        """
        logger.info("Attente de la fin de la validation...")

        # 1. Attendre que validation_queue soit vide
        while not self.validation_queue.empty():
            time.sleep(0.1)

        logger.debug("Queue de validation vide, envoi des signaux d'arrêt aux ValidationWorkers")

        # 2. Envoyer signal d'arrêt à chaque ValidationWorker
        for _ in self.workers:
            self.validation_queue.put(None)

        # 3. Attendre fin de tous les ValidationWorkers
        for thread in self.threads:
            thread.join(timeout=10.0)
            if thread.is_alive():
                logger.warning(f"Thread {thread.name} n'a pas terminé après timeout")

        logger.debug("ValidationWorkers terminés, attente de fin des sauvegardes...")

        # 4. Attendre que save_queue soit vide (CRITIQUE!)
        while not self.save_queue.empty():
            time.sleep(0.1)

        logger.debug("Queue de sauvegarde vide, envoi du signal d'arrêt au SaveWorker")

        # 5. Envoyer signal d'arrêt au SaveWorker
        self.save_queue.put(None)

        # 6. Attendre fin du SaveWorker
        if self.save_thread:
            self.save_thread.join(timeout=10.0)
            if self.save_thread.is_alive():
                logger.warning("SaveWorker n'a pas terminé après timeout")

        logger.info("ValidationWorkerPool terminé (validation + sauvegarde)")

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
