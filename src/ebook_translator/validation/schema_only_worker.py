"""Worker de validation des phases sans `content_checks`.

Phase 0 (`AnalyseChapter`) et glossaire (`list[LLMTermeGlossary]`) sont
validées **entièrement par leur schéma Pydantic**, appliqué par l'executor
avant la mise en queue. Il ne reste rien à vérifier côté worker : l'item
traverse tel quel jusqu'au `SaveWorker`.

Ce worker existe pour que `UnifiedValidationWorker` reste ce qu'il déclare
être — un consommateur de `LineIndexed`. Sa boucle check-by-check copie la
donnée dans un `LineIndexed(dict(...))` et interroge `relevant_indices` :
sur une `list` ou un `BaseModel`, elle produirait une structure aplatie et
casserait la persistance. Le tri se fait donc **en amont**, dans
`ValidationWorkerPool`, sur `phase.content_checks`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..logger import get_logger
from .validation_queue import ValidationItem
from .worker_base import ValidationWorker

logger = get_logger(__name__)


@dataclass
class SchemaOnlyValidationWorker(ValidationWorker[Any]):
    """Passe-plat : la donnée est déjà validée par son schéma.

    `DT` n'est pas contraint ici (contrairement à `UnifiedValidationWorker`
    qui impose `LineIndexed`) : la donnée n'est jamais inspectée, seulement
    relayée au `SaveWorker` via `phase.save_item_builder`.
    """

    def _process(self, item: ValidationItem[Any]) -> Any:
        """Retourne la donnée inchangée.

        Args:
            item: Item sortant de la `ValidationQueue`.

        Returns:
            `item.data`, tel quel — aucune copie, aucun check.
        """
        logger.debug(
            f"[{type(self).__name__}-{self.worker_id}] Chunk {item.chunk.index} "
            f"validé par schéma seul ({self.phase.name})"
        )
        return item.data
