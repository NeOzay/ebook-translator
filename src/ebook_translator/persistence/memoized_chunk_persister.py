"""Stratégie de persistance par mémoïsation chunk-fingerprint.

Sémantique : un fichier `ByteStore` par `outer_key` (typiquement
`chapter_id` ou la constante `"glossary"`). Le contenu est un
`dict[inner_key, M-as-json]` où chaque `inner_key` (fingerprint du
chunk) adresse une contribution indépendante.

Cas d'usage :

- **Phase 0 (analyse littéraire)** : un fichier par chapitre, chaque
  `ChapterPartChunk` produit un `ContexteTraduction` partiel mémoïsé
  par fingerprint. Un fingerprint vu = chunk déjà traité, on saute.
- **Phase glossaire** : un fichier global, chaque chunk (tous chapitres
  confondus) produit ses entrées mémoïsées par fingerprint.

Aucun merge : chaque `inner_key` est une contribution distincte. Le
caller agrège (typiquement via `all_for_outer`) si nécessaire.

Format disque préservé identique à la voie legacy
(`stores.store.Store` utilisé par Phase 0 / glossaire avant migration) :
`{inner_key: M.model_dump_json()}` — valeurs = JSON strings imbriquées
dans un dict JSON externe.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from ..logger import get_logger
from ..stores.byte_store import ByteStore
from .chunk_persister import ChunkPersister

logger = get_logger(__name__)


@runtime_checkable
class MemoChunk(Protocol):
    """Surface attendue d'un chunk mémoïsé par fingerprint.

    Les chunks concrets (`ChapterPartChunk`, chunk de glossaire) doivent
    exposer ces deux propriétés. La logique de calcul du fingerprint
    (typiquement un hash du body) reste à la charge du chunk.
    """

    @property
    def outer_key(self) -> str:
        """Clé de regroupement (chapitre, namespace global)."""
        ...

    @property
    def inner_key(self) -> str:
        """Fingerprint unique de ce chunk dans son `outer_key`."""
        ...


class MemoizedChunkPersister[M: BaseModel](ChunkPersister[M, MemoChunk]):
    """Cache mémoïsé : un fichier par `outer_key`, dict `{inner_key: M-json}`.

    Paramétré sur `M` : la même classe sert pour `ContexteTraduction`
    (Phase 0), `LLMTermeGlossaire` (glossaire), etc. Seule contrainte
    sur `M` : être un `BaseModel` Pydantic (sérialisable JSON).
    """

    def __init__(self, payload_type: type[M]) -> None:
        self.payload_type = payload_type

    def is_chunk_cached(
        self,
        chunk: MemoChunk,
        store: ByteStore,
        fallback: ByteStore | None = None,  # noqa: ARG002
    ) -> bool:
        # Mémoïsation binaire : pas de chaîne fallback (Phase 0/glossaire
        # ne consomment pas une phase précédente). Argument conservé
        # pour respecter la signature du Protocol.
        wrapper = self._read_wrapper(store, chunk.outer_key)
        return chunk.inner_key in wrapper

    def persist(self, chunk: MemoChunk, payload: M, store: ByteStore) -> None:
        with store.lock(chunk.outer_key):
            wrapper = self._read_wrapper(store, chunk.outer_key)
            wrapper[chunk.inner_key] = payload.model_dump_json()
            store.write(
                chunk.outer_key,
                json.dumps(wrapper, ensure_ascii=False, indent=2).encode("utf-8"),
            )

    def load_for_chunk(
        self,
        chunk: MemoChunk,
        store: ByteStore,
        fallback: ByteStore | None = None,  # noqa: ARG002
    ) -> tuple[M | None, set[Any]]:
        wrapper = self._read_wrapper(store, chunk.outer_key)
        raw = wrapper.get(chunk.inner_key)
        if raw is None:
            return None, {chunk.inner_key}
        try:
            return self.payload_type.model_validate_json(raw), set()
        except ValidationError as e:
            logger.warning(
                f"MemoizedChunkPersister: entrée invalide "
                f"{chunk.outer_key}[{chunk.inner_key}] (ignorée): {e}"
            )
            return None, {chunk.inner_key}

    def all_for_outer(self, outer_key: str, store: ByteStore) -> dict[str, M]:
        """Charge toutes les contributions valides d'un `outer_key`.

        Méthode utilitaire pour les phases qui agrègent les contributions
        de tous les chunks d'un chapitre (ex. fusionner les analyses
        partielles). Les entrées invalides sont silencieusement ignorées.
        """

        wrapper = self._read_wrapper(store, outer_key)
        result: dict[str, M] = {}
        for inner_key, raw in wrapper.items():
            try:
                result[inner_key] = self.payload_type.model_validate_json(raw)
            except ValidationError as e:
                logger.warning(
                    f"MemoizedChunkPersister: entrée invalide "
                    f"{outer_key}[{inner_key}] (ignorée): {e}"
                )
        return result

    @staticmethod
    def _read_wrapper(store: ByteStore, outer_key: str) -> dict[str, str]:
        """Lit le dict `{inner_key: json_string}` ; vide si absent / corrompu."""

        raw = store.read(outer_key)
        if raw is None:
            return {}
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(
                f"MemoizedChunkPersister: cache corrompu {outer_key}: {e}"
            )
            return {}
        if not isinstance(parsed, dict):
            return {}
        result: dict[str, str] = {}
        for k, v in parsed.items():  # pyright: ignore[reportUnknownVariableType]
            if isinstance(v, str):
                result[str(k)] = v  # pyright: ignore[reportUnknownArgumentType]
        return result
