"""Socle commun des workers de validation.

`ValidationWorker` porte tout ce qui ne dépend pas de la forme de la donnée :
la boucle de consommation de la `ValidationQueue`, le passage au `SaveWorker`
via `phase.save_item_builder`, le comptage et le log. Les sous-classes ne
fournissent que `_process`, seul endroit qui connaît `DT` :

- `UnifiedValidationWorker` ([unified_worker.py](unified_worker.py)) —
  pipeline check-by-check sur du line-indexed ;
- `SchemaOnlyValidationWorker` ([schema_only_worker.py](schema_only_worker.py))
  — passe-plat pour les phases validées par leur seul schéma.

Le choix entre les deux appartient à `ValidationWorkerPool`, pas au worker.
"""

from __future__ import annotations

import queue
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from itertools import count
from typing import TYPE_CHECKING, Any

from template.types import ConvertibleModel

from ..logger import get_logger
from .validation_queue import SaveQueue, ValidationItem, ValidationQueue

if TYPE_CHECKING:
    from ebook_translator.pipeline.base import PhaseProtocol
    from ebook_translator.segmentation.chunk import ChunkProtocol

    from .failure import ValidationFailure


logger = get_logger(__name__)

counter = count(0)


@dataclass(frozen=True)
class RejectOutcome(Exception):
    """Échec non récupérable : l'item part en rejet, sans sauvegarde.

    Levée par `_process`, rattrapée par `ValidationWorker.run`.
    """

    failures: list[ValidationFailure[Any]]


@dataclass
class ValidationWorker[DT: Any, M: ConvertibleModel[Any] = ConvertibleModel[DT]](ABC):
    """Boucle de consommation d'un thread de validation.

    Attributes:
        validation_queue: Source des items à valider.
        save_queue: Sortie vers le `SaveWorker`.
        phase: Phase courante, réaffectée par le pool à chaque `switch_phase`.
        stop_event: Signal d'arrêt de la boucle.
    """

    validation_queue: ValidationQueue[DT]
    save_queue: SaveQueue[ChunkProtocol, DT]
    phase: PhaseProtocol[ChunkProtocol, DT, M]
    stop_event: threading.Event

    worker_id: int = field(init=False, default_factory=lambda: next(counter))
    validated_count: int = field(init=False, default=0)
    rejected_count: int = field(init=False, default=0)

    @abstractmethod
    def _process(self, item: ValidationItem[DT]) -> DT:
        """Produit la donnée à sauvegarder.

        Args:
            item: Item sortant de la `ValidationQueue`.

        Returns:
            La donnée validée, éventuellement corrigée ou partielle.

        Raises:
            RejectOutcome: Si l'item ne peut pas être sauvegardé.
        """
        ...

    def run(self) -> None:
        """Boucle de consommation. Sortie sur `stop_event.set()`."""

        logger.info(f"[{type(self).__name__}-{self.worker_id}] Démarré")
        while not self.stop_event.is_set():
            try:
                item = self.validation_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                continue

            try:
                data = self._process(item)
                self._save(item, data)
            except RejectOutcome as rej:
                self._reject(item, rej.failures)
            except Exception as e:
                logger.exception(
                    f"[{type(self).__name__}-{self.worker_id}] Erreur traitement: {e}"
                )
                self.validation_queue.mark_rejected()
                self.rejected_count += 1

        logger.info(
            f"[{type(self).__name__}-{self.worker_id}] Arrêté "
            f"(validated={self.validated_count}, rejected={self.rejected_count})"
        )

    def _save(self, item: ValidationItem[DT], data: DT) -> None:
        save_item = self.phase.save_item_builder(item.chunk, data)
        self.save_queue.put(save_item)
        self.validation_queue.mark_validated()
        self.validated_count += 1
        logger.debug(
            f"[{type(self).__name__}-{self.worker_id}] ✅ Chunk {item.chunk.index} validé"
        )

    def _reject(
        self,
        item: ValidationItem[DT],
        failures: list[ValidationFailure[Any]],
    ) -> None:
        self.validation_queue.mark_rejected()
        self.rejected_count += 1
        summary = "\n".join(f"  • {f.error_type}: {f.msg}" for f in failures)
        logger.error(
            f"[{type(self).__name__}-{self.worker_id}] ❌ Chunk {item.chunk.index} "
            f"rejeté:\n{summary}"
        )
