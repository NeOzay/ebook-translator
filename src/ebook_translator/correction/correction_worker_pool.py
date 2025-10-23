"""
Pool de CorrectionWorkers pour traiter les erreurs de traduction en parallèle.

Ce module fournit un pool de N workers qui consomment la ErrorQueue en parallèle,
permettant d'accélérer significativement le traitement des erreurs de traduction.
"""

import threading
from typing import TYPE_CHECKING, Optional

from ..logger import get_logger
from .correction_worker import CorrectionWorker

if TYPE_CHECKING:
    from ..llm import LLM
    from ..store import Store
    from .error_queue import ErrorQueue

logger = get_logger(__name__)


class CorrectionWorkerPool:
    """
    Pool de CorrectionWorkers pour traiter les erreurs en parallèle.

    Ce pool gère N instances de CorrectionWorker qui consomment tous la même
    ErrorQueue de manière thread-safe. Chaque worker traite les erreurs
    indépendamment, permettant un traitement parallèle des corrections LLM.

    Avantages :
    - Performance : Les appels LLM (I/O-bound) se font en parallèle
    - Scalabilité : Configurable via num_workers
    - Thread-safety : ErrorQueue garantit FIFO thread-safe
    - Statistiques agrégées : Combine les stats de tous les workers

    Attributes:
        error_queue: Queue partagée par tous les workers
        llm: Instance LLM pour les corrections
        num_workers: Nombre de workers dans le pool
        workers: Liste des instances CorrectionWorker
        target_language: Langue cible de la traduction

    Example:
        >>> pool = CorrectionWorkerPool(
        ...     error_queue=error_queue,
        ...     llm=llm,
        ...     store=store,
        ...     target_language="fr",
        ...     num_workers=3,
        ... )
        >>> pool.start()
        >>> # ... traductions en cours ...
        >>> pool.stop(timeout=30.0)
        >>> stats = pool.get_aggregated_statistics()
        >>> print(f"Corrected: {stats['corrected']}, Failed: {stats['failed']}")
    """

    def __init__(
        self,
        error_queue: "ErrorQueue",
        llm: "LLM",
        store: "Store",
        target_language: str,
        num_workers: int = 2,
    ):
        """
        Initialise le pool de CorrectionWorkers.

        Args:
            error_queue: Queue partagée contenant les erreurs à corriger
            llm: Instance LLM pour les corrections
            store: Store pour sauvegarder les corrections
            target_language: Code de la langue cible (ex: "fr", "en")
            num_workers: Nombre de workers dans le pool (défaut: 2)

        Raises:
            ValueError: Si num_workers < 1
        """
        if num_workers < 1:
            raise ValueError(f"num_workers doit être >= 1, reçu: {num_workers}")

        self.error_queue = error_queue
        self.llm = llm
        self.num_workers = num_workers
        self.target_language = target_language

        # Créer les workers
        self.workers: list[CorrectionWorker] = []
        for worker_id in range(num_workers):
            worker = CorrectionWorker(
                error_queue=error_queue,
                llm=llm,
                store=store,
                target_language=target_language,
                worker_id=worker_id,  # Pour identification dans les logs
            )
            self.workers.append(worker)

        logger.info(
            f"🔧 CorrectionWorkerPool créé avec {num_workers} worker(s)"
        )

    def start(self) -> None:
        """
        Démarre tous les workers du pool en parallèle.

        Chaque worker tourne dans son propre thread daemon et consomme
        la ErrorQueue de manière thread-safe (FIFO).

        Example:
            >>> pool.start()
            🔧 Démarrage de 3 CorrectionWorkers...
            🔧 [Worker-0] Démarrage du thread de correction
            🔧 [Worker-1] Démarrage du thread de correction
            🔧 [Worker-2] Démarrage du thread de correction
            ✅ 3 CorrectionWorkers démarrés
        """
        logger.info(f"🔧 Démarrage de {self.num_workers} CorrectionWorker(s)...")

        for worker in self.workers:
            worker.start()

        logger.info(f"✅ {self.num_workers} CorrectionWorker(s) démarré(s)")

    def stop(self, timeout: float = 10.0) -> bool:
        """
        Arrête tous les workers du pool proprement.

        Envoie un signal d'arrêt à tous les workers et attend qu'ils
        terminent dans le délai spécifié. Si un worker ne s'arrête pas
        dans le délai, log un warning et continue (le worker est daemon).

        Args:
            timeout: Temps d'attente maximum par worker en secondes (défaut: 10.0)

        Returns:
            True si tous les workers se sont arrêtés dans le délai, False sinon

        Example:
            >>> pool.stop(timeout=30.0)
            🛑 Arrêt de 3 CorrectionWorker(s)...
            ✅ 3/3 CorrectionWorker(s) arrêté(s)
            True
        """
        logger.info(f"🛑 Arrêt de {self.num_workers} CorrectionWorker(s)...")

        all_stopped = True
        stopped_count = 0

        for worker in self.workers:
            success = worker.stop(timeout=timeout)
            if success:
                stopped_count += 1
            else:
                all_stopped = False
                logger.warning(
                    f"⚠️ [Worker-{worker.worker_id}] n'a pas pu s'arrêter dans le délai ({timeout}s)"
                )

        if all_stopped:
            logger.info(f"✅ {stopped_count}/{self.num_workers} CorrectionWorker(s) arrêté(s)")
        else:
            logger.warning(
                f"⚠️ {stopped_count}/{self.num_workers} CorrectionWorker(s) arrêté(s) "
                f"({self.num_workers - stopped_count} timeout)"
            )

        return all_stopped

    def switch_all_stores(self, new_store: "Store") -> None:
        """
        Bascule tous les workers vers un nouveau store (ex: Phase 1 → Phase 2).

        Cette méthode est utilisée lors de la transition entre phases du pipeline
        pour que tous les workers sauvegardent leurs corrections dans le bon store.

        Args:
            new_store: Le nouveau store à utiliser

        Example:
            >>> # Transition Phase 1 → Phase 2
            >>> pool.switch_all_stores(multi_store.refined_store)
            🔄 Basculement de 3 worker(s) vers nouveau store...
            ✅ 3 worker(s) basculé(s)
        """
        logger.info(
            f"🔄 Basculement de {self.num_workers} worker(s) vers nouveau store..."
        )

        for worker in self.workers:
            worker.switch_store(new_store)

        logger.info(f"✅ {self.num_workers} worker(s) basculé(s)")

    def get_aggregated_statistics(self) -> dict:
        """
        Agrège les statistiques de tous les workers du pool.

        Combine les compteurs corrected_count et failed_count de chaque worker
        pour obtenir les statistiques globales du pool.

        Returns:
            Dictionnaire avec statistiques agrégées :
            {
                "corrected": int,      # Total erreurs corrigées
                "failed": int,         # Total erreurs échouées
                "is_alive": bool,      # True si au moins un worker est actif
                "workers_alive": int,  # Nombre de workers actifs
                "by_worker": [...]     # Stats détaillées par worker
            }

        Example:
            >>> stats = pool.get_aggregated_statistics()
            >>> print(f"Total corrections: {stats['corrected']}")
            >>> print(f"Workers actifs: {stats['workers_alive']}/{len(pool.workers)}")
        """
        total_corrected = 0
        total_failed = 0
        workers_alive = 0
        by_worker = []

        for worker in self.workers:
            worker_stats = worker.get_statistics()
            total_corrected += worker_stats["corrected"]
            total_failed += worker_stats["failed"]

            if worker_stats["is_alive"]:
                workers_alive += 1

            by_worker.append({
                "worker_id": worker.worker_id,
                "corrected": worker_stats["corrected"],
                "failed": worker_stats["failed"],
                "is_alive": worker_stats["is_alive"],
            })

        return {
            "corrected": total_corrected,
            "failed": total_failed,
            "is_alive": workers_alive > 0,
            "workers_alive": workers_alive,
            "total_workers": self.num_workers,
            "by_worker": by_worker,
        }

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        stats = self.get_aggregated_statistics()
        return (
            f"CorrectionWorkerPool(\n"
            f"  num_workers={self.num_workers},\n"
            f"  corrected={stats['corrected']},\n"
            f"  failed={stats['failed']},\n"
            f"  workers_alive={stats['workers_alive']}/{self.num_workers}\n"
            f")"
        )
