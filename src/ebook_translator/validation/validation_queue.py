"""
Queue thread-safe pour gérer les validations à effectuer.

Ce module fournit une infrastructure pour collecter et distribuer
les chunks à valider aux ValidationWorkers.
"""

import queue
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..segment import Chunk


@dataclass
class ValidationItem:
    """
    Représente un chunk et ses traductions à valider.

    Attributes:
        chunk: Le chunk avec textes originaux
        translated_texts: Traductions à valider {line_index: translated_text}

    Example:
        >>> item = ValidationItem(
        ...     chunk=chunk,
        ...     translated_texts={0: "Bonjour", 1: "Monde"}
        ... )
    """

    chunk: "Chunk"
    translated_texts: dict[int, str]

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        return (
            f"ValidationItem(chunk={self.chunk.index}, "
            f"lines={len(self.translated_texts)})"
        )


@dataclass
class SaveItem:
    """
    Représente un résultat de validation à sauvegarder dans le Store.

    Cette classe encapsule toutes les données nécessaires pour que le SaveWorker
    puisse sauvegarder une traduction validée sans bloquer les ValidationWorkers.

    Attributes:
        chunk: Le chunk validé (pour callback et logging)
        final_translations: Traductions finales après validation {line_index: translated_text}
        source_files: Mapping par fichier source {source_file: {line_index_str: translated_text}}
                     Résultat de build_translation_map(chunk, final_translations)
                     Note: Les clés de ligne sont des strings (format JSON)

    Example:
        >>> from ebook_translator.translation.engine import build_translation_map
        >>> translation_map = build_translation_map(chunk, {0: "Bonjour", 1: "Monde"})
        >>> item = SaveItem(
        ...     chunk=chunk,
        ...     final_translations={0: "Bonjour", 1: "Monde"},
        ...     source_files=translation_map
        ... )
    """

    chunk: "Chunk"
    final_translations: dict[int, str]
    source_files: dict[str, dict[str, str]]  # Clés de ligne sont des strings (JSON)

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        return (
            f"SaveItem(chunk={self.chunk.index}, "
            f"files={len(self.source_files)}, "
            f"lines={len(self.final_translations)})"
        )


@dataclass
class ValidationQueueStats:
    """
    Statistiques de la queue de validation.

    Attributes:
        total_submitted: Nombre total d'items soumis
        validated: Nombre d'items validés avec succès
        rejected: Nombre d'items rejetés (échec validation)
        pending: Nombre d'items en attente
    """

    total_submitted: int = 0
    validated: int = 0
    rejected: int = 0
    pending: int = 0


class ValidationQueue:
    """
    Queue thread-safe pour gérer les validations de chunks.

    Cette classe fournit une interface thread-safe pour soumettre des chunks
    à valider, les récupérer pour validation, et suivre leur statut.

    Example:
        >>> validation_queue = ValidationQueue(maxsize=100)
        >>> validation_queue.put(ValidationItem(chunk, translations))
        >>> item = validation_queue.get(timeout=5.0)
        >>> # ... valider ...
        >>> if success:
        ...     validation_queue.mark_validated()
        ... else:
        ...     validation_queue.mark_rejected()
    """

    def __init__(self, maxsize: int = 100):
        """
        Initialise la queue de validation.

        Args:
            maxsize: Taille maximale de la queue (défaut: 100)
        """
        self._queue: queue.Queue[Optional[ValidationItem]] = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._stats = ValidationQueueStats()

    def put(
        self, item: Optional[ValidationItem], block: bool = True, timeout: Optional[float] = None
    ) -> None:
        """
        Ajoute un item à la queue.

        Args:
            item: L'item à valider (ou None pour signal d'arrêt)
            block: Si True, bloque si la queue est pleine (défaut: True)
            timeout: Temps d'attente maximum en secondes (None = infini)

        Raises:
            queue.Full: Si la queue est pleine et block=False ou timeout expiré
        """
        if item is not None:
            with self._lock:
                self._stats.total_submitted += 1
                self._stats.pending += 1

        self._queue.put(item, block=block, timeout=timeout)

    def get(
        self, block: bool = True, timeout: Optional[float] = None
    ) -> Optional[ValidationItem]:
        """
        Récupère un item depuis la queue.

        Args:
            block: Si True, bloque si la queue est vide (défaut: True)
            timeout: Temps d'attente maximum en secondes (None = infini)

        Returns:
            ValidationItem ou None si signal d'arrêt ou timeout

        Raises:
            queue.Empty: Si la queue est vide et block=False ou timeout expiré
        """
        try:
            return self._queue.get(block=block, timeout=timeout)
        except queue.Empty:
            if not block or timeout is not None:
                return None
            raise

    def mark_validated(self) -> None:
        """Marque un item comme validé avec succès."""
        with self._lock:
            self._stats.validated += 1
            self._stats.pending -= 1

    def mark_rejected(self) -> None:
        """Marque un item comme rejeté (échec validation)."""
        with self._lock:
            self._stats.rejected += 1
            self._stats.pending -= 1

    def get_statistics(self) -> ValidationQueueStats:
        """
        Récupère les statistiques actuelles de la queue.

        Returns:
            Copie des statistiques (thread-safe)
        """
        with self._lock:
            return ValidationQueueStats(
                total_submitted=self._stats.total_submitted,
                validated=self._stats.validated,
                rejected=self._stats.rejected,
                pending=self._stats.pending,
            )

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

        Note: La taille peut changer entre l'appel et l'utilisation
        dans un environnement multi-thread.

        Returns:
            Nombre d'éléments approximatif dans la queue
        """
        return self._queue.qsize()

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        stats = self.get_statistics()
        return (
            f"ValidationQueue(\n"
            f"  pending={stats.pending}, "
            f"  validated={stats.validated}, "
            f"  rejected={stats.rejected}\n"
            f")"
        )


class SaveQueue:
    """
    Queue thread-safe pour gérer les sauvegardes à effectuer.

    Cette queue permet de séparer la validation (multi-thread) de la sauvegarde
    (single-thread), éliminant ainsi les conflits d'écriture (WinError 32 sur Windows).

    Architecture:
        ValidationWorkers → SaveQueue → SaveWorker (unique) → Store

    Example:
        >>> save_queue = SaveQueue(maxsize=100)
        >>> save_queue.put(SaveItem(chunk, translations, translation_map))
        >>> item = save_queue.get(timeout=5.0)
        >>> # ... sauvegarder dans Store ...
        >>> save_queue.mark_saved()
    """

    def __init__(self, maxsize: int = 100):
        """
        Initialise la queue de sauvegarde.

        Args:
            maxsize: Taille maximale de la queue (défaut: 100)
        """
        self._queue: queue.Queue[Optional[SaveItem]] = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._stats = {"saved": 0, "pending": 0, "errors": 0}

    def put(
        self, item: Optional[SaveItem], block: bool = True, timeout: Optional[float] = None
    ) -> None:
        """
        Ajoute un item à la queue de sauvegarde.

        Args:
            item: L'item à sauvegarder (ou None pour signal d'arrêt)
            block: Si True, bloque si la queue est pleine (défaut: True)
            timeout: Temps d'attente maximum en secondes (None = infini)

        Raises:
            queue.Full: Si la queue est pleine et block=False ou timeout expiré
        """
        if item is not None:
            with self._lock:
                self._stats["pending"] += 1

        self._queue.put(item, block=block, timeout=timeout)

    def get(
        self, block: bool = True, timeout: Optional[float] = None
    ) -> Optional[SaveItem]:
        """
        Récupère un item depuis la queue.

        Args:
            block: Si True, bloque si la queue est vide (défaut: True)
            timeout: Temps d'attente maximum en secondes (None = infini)

        Returns:
            SaveItem ou None si signal d'arrêt ou timeout

        Raises:
            queue.Empty: Si la queue est vide et block=False ou timeout expiré
        """
        try:
            return self._queue.get(block=block, timeout=timeout)
        except queue.Empty:
            if not block or timeout is not None:
                return None
            raise

    def mark_saved(self) -> None:
        """Marque un item comme sauvegardé avec succès."""
        with self._lock:
            self._stats["saved"] += 1
            self._stats["pending"] -= 1

    def mark_error(self) -> None:
        """Marque un item comme ayant échoué lors de la sauvegarde."""
        with self._lock:
            self._stats["errors"] += 1
            self._stats["pending"] -= 1

    def get_statistics(self) -> dict[str, int]:
        """
        Récupère les statistiques actuelles de la queue.

        Returns:
            Dictionnaire avec saved, pending, errors (thread-safe)
        """
        with self._lock:
            return {
                "saved": self._stats["saved"],
                "pending": self._stats["pending"],
                "errors": self._stats["errors"],
            }

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

        Note: La taille peut changer entre l'appel et l'utilisation
        dans un environnement multi-thread.

        Returns:
            Nombre d'éléments approximatif dans la queue
        """
        return self._queue.qsize()

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        stats = self.get_statistics()
        return (
            f"SaveQueue(\n"
            f"  pending={stats['pending']}, "
            f"  saved={stats['saved']}, "
            f"  errors={stats['errors']}\n"
            f")"
        )
