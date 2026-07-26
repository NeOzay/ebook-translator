"""Queues thread-safe pour le pipeline validation/save.

`ValidationItem[DT]` porte la **vue TypedDict** consommée par le worker.
Pas de Pydantic dans la queue — `M → DT` n'est typiquement pas
réversible (champs dérivés / ClassVars / metadata absents du `build()`).
La conversion schéma se fait à deux endroits stables :

- côté **executor** (post-LLM) : `payload_type.model_validate(raw)` puis
  `payload.build()` → DT injecté dans la queue.
- côté **worker** (post-LLM retry) : `payload_type.model_validate_json(raw)`
  puis `build()` → DT mergé.

`SaveItem[ChunkType, DT]` reste self-contained (cf. Bloc A) : embarque
son propre persister + byte_store.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ebook_translator.persistence.chunk_persister import ChunkPersister
from ebook_translator.segmentation.chunk import ChunkProtocol
from ebook_translator.stores.byte_store import ByteStore

from .failure import ValidationFailure

if TYPE_CHECKING:
    from ..pipeline.context import ChunkContext


@dataclass
class ValidationItem[DT: Any = Any]:
    """Unité de travail soumise au worker de validation.

    Attributes:
        chunk: Chunk source (textes d'origine + métadonnées).
        chunk_info: Contexte d'exécution (phase, index, chunk précédent).
        data: Vue TypedDict de la sortie LLM (déjà schéma-validée par
            l'executor). Pour les phases de traduction : `dict[int, str]`.
        attempt: Numéro de la tentative courante (1 = T1, 2 = T2, …).
        failures: Diagnostics cumulés des tentatives précédentes. Le
            worker consulte la dernière `failure` pour router via
            `RETRY_REGISTRY` ; la liste sert au log et au tracing.
    """

    chunk: ChunkProtocol
    chunk_info: ChunkContext
    data: DT
    attempt: int = 0
    failures: list[ValidationFailure[Any]] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"ValidationItem(chunk={self.chunk.index}, "
            f"data={type(self.data).__name__}, "
            f"attempt={self.attempt}, failures={len(self.failures)})"
        )


@dataclass
class SaveItem[ChunkType: ChunkProtocol = ChunkProtocol, DT: Any = Any]:
    """Unité de travail self-contained pour le `SaveWorker`.

    Le worker se contente d'appeler `persister.persist(chunk, data, byte_store)` ;
    aucune connaissance de la phase d'origine n'est requise.
    """

    chunk: ChunkType
    data: DT
    persister: ChunkPersister[ChunkType, DT]
    byte_store: ByteStore
    on_save: Callable[[SaveItem[ChunkType, DT]], None] | None = None

    def __repr__(self) -> str:
        return (
            f"SaveItem(chunk={self.chunk.index}, "
            f"payload={type(self.data).__name__}, "
            f"persister={type(self.persister).__name__})"
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


class ValidationQueue[DT: Any = Any]:
    """Queue thread-safe paramétrée sur la vue TypedDict `DT`."""

    def __init__(self, maxsize: int = 100):
        """
        Initialise la queue de validation.

        Args:
            maxsize: Taille maximale de la queue (défaut: 100)
        """
        self._queue: queue.Queue[ValidationItem[DT] | None] = queue.Queue(
            maxsize=maxsize
        )
        self._lock = threading.Lock()
        self._stats = ValidationQueueStats()
        self._in_progress = (
            0  # Items sortis de la queue mais pas encore validés/rejetés
        )

    def put(
        self,
        item: ValidationItem[DT] | None,
        block: bool = True,
        timeout: float | None = None,
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
        self, block: bool = True, timeout: float | None = None
    ) -> ValidationItem[DT] | None:
        """
        Récupère un item depuis la queue.

        Args:
            block: Si True, bloque si la queue est vide (défaut: True)
            timeout: Temps d'attente maximum en secondes (None = infini)

        Returns:
            ValidationItem ou None UNIQUEMENT si signal d'arrêt explicite (put(None))

        Raises:
            queue.Empty: Si timeout expiré (NE retourne PAS None sur timeout)

        Note:
            Si timeout expire, lève queue.Empty au lieu de retourner None.
            Cela permet de distinguer timeout (normal) vs signal d'arrêt (None).
        """
        item = self._queue.get(block=block, timeout=timeout)
        if item is not None:
            with self._lock:
                self._in_progress += 1
        return item

    def mark_validated(self) -> None:
        """Marque un item comme validé avec succès."""
        with self._lock:
            self._stats.validated += 1
            self._stats.pending -= 1
            self._in_progress -= 1

    def mark_rejected(self) -> None:
        """Marque un item comme rejeté (échec validation)."""
        with self._lock:
            self._stats.rejected += 1
            self._stats.pending -= 1
            self._in_progress -= 1

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

        ATTENTION: Ne garantit PAS que tout le travail est terminé!
        Utilisez is_idle() pour vérifier qu'il n'y a aucun item en cours.

        Returns:
            True si la queue est vide, False sinon
        """
        return self._queue.empty()

    def is_idle(self) -> bool:
        """
        Vérifie si queue vide ET aucun item en cours de traitement.

        C'est la méthode à utiliser pour savoir si on peut arrêter les workers
        en toute sécurité (garantit qu'aucun travail n'est perdu).

        Returns:
            True si vraiment idle (queue vide + aucun en cours), False sinon
        """
        with self._lock:
            return self._queue.empty() and self._in_progress == 0

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


class SaveQueue[ChunkType: ChunkProtocol = ChunkProtocol, DT: Any = Any]:
    """Queue thread-safe paramétrée sur le couple `(ChunkType, DT)`.

    `ValidationWorkers → SaveQueue → SaveWorker (unique) → ByteStore`.
    """

    def __init__(self, maxsize: int = 100):
        """
        Initialise la queue de sauvegarde.

        Args:
            maxsize: Taille maximale de la queue (défaut: 100)
        """
        self._queue: queue.Queue[SaveItem[ChunkType, DT] | None] = queue.Queue(
            maxsize=maxsize
        )
        self._lock = threading.Lock()
        self._stats = {"saved": 0, "pending": 0, "errors": 0}
        self._in_progress = 0  # Items sortis de la queue mais pas encore sauvegardés

    def put(
        self,
        item: SaveItem[ChunkType, DT] | None,
        block: bool = True,
        timeout: float | None = None,
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
        self, block: bool = True, timeout: float | None = None
    ) -> SaveItem[ChunkType, DT] | None:
        """
        Récupère un item depuis la queue.

        Args:
            block: Si True, bloque si la queue est vide (défaut: True)
            timeout: Temps d'attente maximum en secondes (None = infini)

        Returns:
            SaveItem ou None UNIQUEMENT si signal d'arrêt explicite (put(None))

        Raises:
            queue.Empty: Si timeout expiré (NE retourne PAS None sur timeout)

        Note:
            Si timeout expire, lève queue.Empty au lieu de retourner None.
            Cela permet de distinguer timeout (normal) vs signal d'arrêt (None).
        """
        item = self._queue.get(block=block, timeout=timeout)
        if item is not None:
            with self._lock:
                self._in_progress += 1
        return item

    def mark_saved(self) -> None:
        """Marque un item comme sauvegardé avec succès."""
        with self._lock:
            self._stats["saved"] += 1
            self._stats["pending"] -= 1
            self._in_progress -= 1

    def mark_error(self) -> None:
        """Marque un item comme ayant échoué lors de la sauvegarde."""
        with self._lock:
            self._stats["errors"] += 1
            self._stats["pending"] -= 1
            self._in_progress -= 1

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

        ATTENTION: Ne garantit PAS que tout le travail est terminé!
        Utilisez is_idle() pour vérifier qu'il n'y a aucun item en cours.

        Returns:
            True si la queue est vide, False sinon
        """
        return self._queue.empty()

    def is_idle(self) -> bool:
        """
        Vérifie si queue vide ET aucun item en cours de sauvegarde.

        C'est la méthode à utiliser pour savoir si on peut arrêter le SaveWorker
        en toute sécurité (garantit qu'aucune sauvegarde n'est perdue).

        Returns:
            True si vraiment idle (queue vide + aucun en cours), False sinon
        """
        with self._lock:
            return self._queue.empty() and self._in_progress == 0

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
