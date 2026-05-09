"""Base abstraite des stratégies de persistance par chunk.

Un `ChunkPersister[M, ChunkT]` encapsule **comment** un payload `M` issu
d'un `ChunkT` est mémoïsé / lu / écrit dans un `ByteStore`. Les
implémentations concrètes choisissent la sémantique :

- `LineIndexedPersister` : un fichier par fichier source HTML, projection
  chunk-local idx ↔ `(file_name, tag_key.index)`, merge cross-chunks,
  fallback chain inter-phases.
- `MemoizedChunkPersister` : un fichier par `outer_key` (chapitre,
  glossaire), dict `{inner_key: M-as-json}`, mémoïsation binaire par
  fingerprint de chunk.

Le persister est l'unique point qui connaît à la fois le shape du
modèle et la sémantique chunk. Modèles et stores restent agnostiques.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..stores.byte_store import ByteStore


class ChunkPersister[M, ChunkT](ABC):
    """Stratégie de persistance d'un payload `M` lié à un chunk `ChunkT`.

    Les méthodes opèrent toutes sur un `ByteStore` injecté (et un
    fallback optionnel pour les stratégies qui supportent le chaînage
    inter-phases). Aucun état n'est conservé sur le persister entre
    appels — il est typiquement instancié comme attribut de classe sur
    la phase concrète.
    """

    @abstractmethod
    def is_chunk_cached(
        self,
        chunk: ChunkT,
        store: ByteStore,
        fallback: ByteStore | None = None,
    ) -> bool:
        """Vrai si le chunk est intégralement disponible dans `store`.

        Pour les stratégies indexées par fragment (line-indexed), tous
        les fragments du chunk doivent être présents. Pour les
        stratégies binaires (mémoïsation par fingerprint), il suffit que
        l'entrée existe.

        Si `fallback` est fourni et que le store principal ne couvre pas
        tout, la stratégie peut consulter le fallback (selon
        implémentation).
        """

    @abstractmethod
    def persist(self, chunk: ChunkT, payload: M, store: ByteStore) -> None:
        """Écrit `payload` dans `store` selon la stratégie.

        Peut impliquer plusieurs écritures (line-indexed, un fichier par
        page traversée) ou une seule (mémoïsation). La méthode gère
        elle-même le locking et les éventuels merges avec l'existant.
        """

    @abstractmethod
    def load_for_chunk(
        self,
        chunk: ChunkT,
        store: ByteStore,
        fallback: ByteStore | None = None,
    ) -> tuple[M | None, set[Any]]:
        """Reconstruit le payload du chunk depuis `store`.

        Returns:
            Un tuple `(payload, missing_keys)`.

            - `payload` est `None` si rien d'utilisable n'a été trouvé,
              sinon une instance de `M` reconstituée à partir des
              entrées disponibles (potentiellement partielle).
            - `missing_keys` énumère les éléments absents (indices
              chunk-local pour line-indexed, `{inner_key}` pour
              mémoïsation). Vide si tout est présent.
        """
