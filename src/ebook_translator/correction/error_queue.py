"""
Queue thread-safe pour gérer les erreurs de traduction à corriger.

Ce module fournit une infrastructure pour collecter et traiter de manière
asynchrone les erreurs de traduction (lignes manquantes, fragment mismatch)
via un thread de correction dédié.
"""

import queue
import threading
from dataclasses import dataclass, field
from typing import Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..segment import Chunk

ErrorType = Literal["missing_lines", "fragment_mismatch"]


@dataclass
class ErrorItem:
    """
    Représente une erreur de traduction à corriger.

    Attributes:
        chunk: Le chunk contenant l'erreur
        error_type: Type d'erreur ("missing_lines" ou "fragment_mismatch")
        error_data: Données détaillées de l'erreur (dépend du type)
        retry_count: Nombre de tentatives de correction déjà effectuées
        max_retries: Nombre maximum de tentatives autorisées
        phase: Phase du pipeline ("initial" ou "refined")

    Example error_data formats:
        missing_lines: {
            "missing_indices": [5, 10, 15],
            "error_message": "...",
            "translated_texts": {...}
        }
        fragment_mismatch: {
            "expected_count": 3,
            "actual_count": 2,
            "original_fragments": [...],
            "translated_segments": [...],
            "tag_key": TagKey(...),
            "page": HtmlPage(...)
        }
    """

    chunk: "Chunk"
    error_type: ErrorType
    error_data: dict
    retry_count: int = 0
    max_retries: int = 2
    phase: Literal["initial", "refined"] = "initial"

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        return (
            f"ErrorItem(chunk={self.chunk.index}, type={self.error_type}, "
            f"retries={self.retry_count}/{self.max_retries}, phase={self.phase})"
        )


@dataclass
class ErrorQueueStats:
    """
    Statistiques de la queue d'erreurs.

    Attributes:
        total_errors: Nombre total d'erreurs soumises
        corrected: Nombre d'erreurs corrigées avec succès
        failed: Nombre d'erreurs non récupérables
        pending: Nombre d'erreurs en attente de traitement
        by_type: Statistiques par type d'erreur
    """

    total_errors: int = 0
    corrected: int = 0
    failed: int = 0
    pending: int = 0
    by_type: dict[ErrorType, dict[str, int]] = field(default_factory=dict)

    def __post_init__(self):
        """Initialise les compteurs par type si vide."""
        if not self.by_type:
            self.by_type = {
                "missing_lines": {"submitted": 0, "corrected": 0, "failed": 0},
                "fragment_mismatch": {"submitted": 0, "corrected": 0, "failed": 0},
            }


class ErrorQueue:
    """
    Queue thread-safe pour gérer les erreurs de traduction.

    Cette classe fournit une interface thread-safe pour soumettre des erreurs
    de traduction, les récupérer pour correction, et suivre leur statut.

    Example:
        >>> error_queue = ErrorQueue(maxsize=100)
        >>> error_queue.put(ErrorItem(chunk, "missing_lines", {...}))
        >>> item = error_queue.get(timeout=5.0)
        >>> # ... tenter correction ...
        >>> if success:
        ...     error_queue.mark_corrected(item)
        ... else:
        ...     error_queue.mark_failed(item)
    """

    def __init__(self, maxsize: int = 100):
        """
        Initialise la queue d'erreurs.

        Args:
            maxsize: Taille maximale de la queue (défaut: 100)
        """
        self._queue: queue.Queue[ErrorItem] = queue.Queue(maxsize=maxsize)
        self._failed: list[ErrorItem] = []
        self._lock = threading.Lock()
        self._stats = ErrorQueueStats()

    def put(self, item: ErrorItem, block: bool = True, timeout: Optional[float] = None) -> None:
        """
        Ajoute une erreur à la queue.

        Args:
            item: L'erreur à ajouter
            block: Si True, bloque si la queue est pleine (défaut: True)
            timeout: Temps d'attente maximum en secondes (None = infini)

        Raises:
            queue.Full: Si la queue est pleine et block=False ou timeout expiré
        """
        with self._lock:
            self._stats.total_errors += 1
            self._stats.by_type[item.error_type]["submitted"] += 1
            self._stats.pending += 1

        self._queue.put(item, block=block, timeout=timeout)

    def get(self, block: bool = True, timeout: Optional[float] = None) -> Optional[ErrorItem]:
        """
        Récupère une erreur depuis la queue.

        Args:
            block: Si True, bloque si la queue est vide (défaut: True)
            timeout: Temps d'attente maximum en secondes (None = infini)

        Returns:
            ErrorItem ou None si timeout expiré (en mode non-bloquant)

        Raises:
            queue.Empty: Si la queue est vide et block=False ou timeout expiré
        """
        try:
            return self._queue.get(block=block, timeout=timeout)
        except queue.Empty:
            if not block or timeout is not None:
                return None
            raise

    def mark_corrected(self, item: ErrorItem) -> None:
        """
        Marque une erreur comme corrigée avec succès.

        Args:
            item: L'erreur qui a été corrigée
        """
        with self._lock:
            self._stats.corrected += 1
            self._stats.by_type[item.error_type]["corrected"] += 1
            self._stats.pending -= 1

    def mark_failed(self, item: ErrorItem) -> None:
        """
        Marque une erreur comme non récupérable.

        Args:
            item: L'erreur qui n'a pas pu être corrigée
        """
        with self._lock:
            self._failed.append(item)
            self._stats.failed += 1
            self._stats.by_type[item.error_type]["failed"] += 1
            self._stats.pending -= 1

    def get_statistics(self) -> ErrorQueueStats:
        """
        Récupère les statistiques actuelles de la queue.

        Returns:
            Copie des statistiques (thread-safe)
        """
        with self._lock:
            # Retourner une copie pour éviter les modifications concurrentes
            return ErrorQueueStats(
                total_errors=self._stats.total_errors,
                corrected=self._stats.corrected,
                failed=self._stats.failed,
                pending=self._stats.pending,
                by_type={k: dict(v) for k, v in self._stats.by_type.items()},
            )

    def get_failed_items(self) -> list[ErrorItem]:
        """
        Récupère la liste des erreurs non récupérables.

        Returns:
            Liste des ErrorItem qui ont échoué (copie pour thread-safety)
        """
        with self._lock:
            return list(self._failed)

    def empty(self) -> bool:
        """
        Vérifie si la queue est vide.

        Returns:
            True si la queue est vide, False sinon
        """
        return self._queue.empty()

    def qsize(self) -> int:
        """
        Retourne la taille approximative de la queue.

        Note: La taille peut changer entre l'appel et l'utilisation du résultat
        dans un environnement multi-thread.

        Returns:
            Nombre d'éléments approximatif dans la queue
        """
        return self._queue.qsize()

    def clear(self) -> None:
        """
        Vide complètement la queue.

        Attention: Cette opération n'est pas atomique. Des éléments peuvent
        être ajoutés pendant le vidage.
        """
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        stats = self.get_statistics()
        return (
            f"ErrorQueue(\n"
            f"  pending={stats.pending}, "
            f"  corrected={stats.corrected}, "
            f"  failed={stats.failed}\n"
            f"  by_type={stats.by_type}\n"
            f")"
        )
