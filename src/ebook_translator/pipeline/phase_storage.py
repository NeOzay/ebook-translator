"""Persistance d'une phase : compose `ChunkPersister` + `ByteStore`(s).

Extrait de `PhaseBase` pour découpler la phase (configuration, hooks LLM)
de l'I/O cache (lecture/écriture/fallback inter-phases). La phase se
contente d'instancier `PhaseStorage` une fois et de proxyer (ou
d'exposer) son surface aux callers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..persistence.chunk_persister import ChunkPersister
from ..segmentation.chunk import ChunkProtocol
from ..stores.byte_store import ByteStore

if TYPE_CHECKING:
    from ..validation import SaveItem


class PhaseStorage[ChunkType: ChunkProtocol, DT]:
    """Surface unifiée d'I/O cache d'une phase.

    Wrap un `ChunkPersister` + un `ByteStore` principal + un fallback
    optionnel. Toute la logique de routage (qui consulte quoi, dans quel
    ordre) vit dans le persister ; `PhaseStorage` n'est qu'un binder.
    """

    def __init__(
        self,
        persister: ChunkPersister[ChunkType, DT],
        byte_store: ByteStore,
        byte_fallback_store: ByteStore | None = None,
    ) -> None:
        self.persister = persister
        self.byte_store = byte_store
        self.byte_fallback_store = byte_fallback_store

    def is_cached(self, chunk: ChunkType) -> bool:
        return self.persister.is_chunk_cached(
            chunk, self.byte_store, self.byte_fallback_store
        )

    def load(self, chunk: ChunkType) -> tuple[DT | None, set[int]]:
        return self.persister.load_for_chunk(
            chunk, self.byte_store, self.byte_fallback_store
        )

    def persist(self, chunk: ChunkType, data: DT) -> None:
        self.persister.persist(chunk, data, self.byte_store)

    def save_item(self, chunk: ChunkType, data: DT) -> SaveItem[ChunkType, DT]:
        from ..validation import SaveItem

        return SaveItem(chunk, data, self.persister, self.byte_store)
