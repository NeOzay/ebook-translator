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
from typing import Any, Protocol, override, runtime_checkable

from pydantic import TypeAdapter, ValidationError

from ..logger import get_logger
from ..segmentation.chunk import ChunkProtocol
from ..stores.byte_store import ByteStore
from .chunk_persister import ChunkPersister

logger = get_logger(__name__)


@runtime_checkable
class MemoChunk(ChunkProtocol, Protocol):
    """Surface attendue d'un chunk mémoïsé par fingerprint.

    Étend `ChunkProtocol` (pour satisfaire la borne du `ChunkPersister`)
    et ajoute deux propriétés : `outer_key` (regroupement) et `inner_key`
    (fingerprint). Les chunks concrets (`ChapterPartChunk`, chunk de
    glossaire) implémentent déjà `ChunkProtocol` et exposent ces deux
    accesseurs.
    """

    @property
    def outer_key(self) -> str:
        """Clé de regroupement (chapitre, namespace global)."""
        ...

    @property
    def inner_key(self) -> str:
        """Fingerprint unique de ce chunk dans son `outer_key`."""
        ...


class MemoizedChunkPersister[TD: Any](ChunkPersister[MemoChunk, TD]):
    """Cache mémoïsé : un fichier par `outer_key`, dict `{inner_key: TD-json}`.

    Paramétré sur `TD` : la même classe sert pour `AnalyseChapter`
    (Phase 0, un `BaseModel`) et `list[LLMTermeGlossary]` (glossaire, une
    liste de `TypedDict`). La (dé)sérialisation passe par un
    `TypeAdapter`, qui traite les deux cas — pour un `BaseModel`, le JSON
    produit est identique à `model_dump_json()`, donc le format disque
    des caches existants est préservé.
    """

    def __init__(self, payload_type: type[TD]) -> None:
        self.payload_type = payload_type
        self._adapter: TypeAdapter[TD] = TypeAdapter(payload_type)

    @override
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

    @override
    def persist(self, chunk: MemoChunk, data: TD, store: ByteStore) -> None:
        with store.lock(chunk.outer_key):
            wrapper = self._read_wrapper(store, chunk.outer_key)
            wrapper[chunk.inner_key] = self._adapter.dump_json(data).decode("utf-8")
            store.write(
                chunk.outer_key,
                json.dumps(wrapper, ensure_ascii=False, indent=2).encode("utf-8"),
            )

    @override
    def load_for_chunk(
        self,
        chunk: MemoChunk,
        store: ByteStore,
        fallback: ByteStore | None = None,  # noqa: ARG002
    ) -> tuple[TD | None, set[Any]]:
        wrapper = self._read_wrapper(store, chunk.outer_key)
        raw = wrapper.get(chunk.inner_key)
        if raw is None:
            return None, {chunk.inner_key}
        try:
            return self._adapter.validate_json(raw), set()
        except ValidationError as e:
            logger.warning(
                f"MemoizedChunkPersister: entrée invalide "
                f"{chunk.outer_key}[{chunk.inner_key}] (ignorée): {e}"
            )
            return None, {chunk.inner_key}

    def all_for_outer(self, outer_key: str, store: ByteStore) -> dict[str, TD]:
        """Charge toutes les contributions valides d'un `outer_key`.

        Méthode utilitaire pour les phases qui agrègent les contributions
        de tous les chunks d'un chapitre (ex. fusionner les analyses
        partielles). Les entrées invalides sont silencieusement ignorées.
        """

        wrapper = self._read_wrapper(store, outer_key)
        result: dict[str, TD] = {}
        for inner_key, raw in wrapper.items():
            try:
                result[inner_key] = self._adapter.validate_json(raw)
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
            logger.warning(f"MemoizedChunkPersister: cache corrompu {outer_key}: {e}")
            return {}
        if not isinstance(parsed, dict):
            return {}

        result: dict[str, str] = {}
        for k, v in parsed.items():  # pyright: ignore[reportUnknownVariableType]
            if isinstance(v, str):
                result[str(k)] = v  # pyright: ignore[reportUnknownArgumentType]
        return result
