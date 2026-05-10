"""Stratégie de persistance line-indexée (phases traduction).

Sémantique : un chunk produit un TypedDict chunk-local
(`dict[chunk_idx, translation]`). Cette stratégie projette ce payload
sur N fichiers `ByteStore` distincts (un par `file_name` HTML traversé
par le chunk), où chaque fichier stocke un TypedDict file-local
(`dict[file_idx, translation]`) accumulant les contributions de **tous**
les chunks ayant traversé ce fichier source.

Le format disque est la forme « donnée pure » produite par
`LineIndexedTranslation.serialized_build()` (un objet JSON plat
`{"0": "T0", "1": "T1"}`), pas la forme Pydantic enveloppée
(`{"lines": {...}}`). Pydantic n'intervient qu'au parsing de la sortie
LLM côté caller ; le persister n'en dépend pas.

Projection chunk-local → file-local : pour chaque fragment du body,
`enumerate(chunk.fetch_body())` donne le chunk_idx (clé du payload
chunk-local) et `tag_key.index` donne le file_idx (clé du payload
file-local stocké).

Fallback : un `ByteStore` secondaire peut être consulté pour les indices
absents du store principal — utilisé pour le chaînage Phase 1 → Phase 2
(refinement lit Phase 1 si Phase 2 n'a pas encore caché la ligne).
"""

from __future__ import annotations

from typing import override

from pydantic import ValidationError

from template.types import ConvertibleModel

from ..logger import get_logger
from ..segmentation.chunk import ChunkProtocol
from ..stores.byte_store import ByteStore
from .chunk_persister import ChunkPersister

logger = get_logger(__name__)


class LineIndexedPersister(ChunkPersister[ChunkProtocol, dict[int, str]]):
    """Cache line-indexé : un fichier ByteStore par fichier source HTML.

    Disque et API en TypedDict pur (`dict[int, str]`). La (dé)sérialisation
    passe par `model.target_adapter()` — le `ConvertibleModel` reste la
    source de vérité du shape TD ; si la forme change, seul le modèle est
    touché.
    """

    def __init__(self, model: type[ConvertibleModel[dict[int, str]]]) -> None:
        self._model = model
        self._adapter = model.target_adapter()

    @override
    def is_chunk_cached(
        self,
        chunk: ChunkProtocol,
        store: ByteStore,
        fallback: ByteStore | None = None,
    ) -> bool:
        for page, tag_key, _ in chunk.fetch_body():
            file_name = str(page.epub_html.file_name)
            file_idx = int(tag_key.index)
            payload = self._load_file(store, file_name) or self._load_file(
                fallback, file_name
            )
            if payload is None or file_idx not in payload:
                return False
        return True

    @override
    def persist(
        self,
        chunk: ChunkProtocol,
        data: dict[int, str],
        store: ByteStore,
    ) -> None:
        # Regroupe les lignes du payload chunk-local par file_name de
        # destination, en remappant chunk_idx → file_idx (= int(tag_key.index)).
        by_file: dict[str, dict[int, str]] = {}
        for chunk_idx, (page, tag_key, _) in enumerate(chunk.fetch_body()):
            line_text = data.get(chunk_idx)
            if line_text is None:
                # Payload partiel sur cet index : on ne caste pas une ligne
                # absente (un retry ciblé la fournira plus tard).
                continue
            file_name = str(page.epub_html.file_name)
            file_idx = int(tag_key.index)
            if file_name not in by_file:
                by_file[file_name] = {}
            by_file[file_name][file_idx] = line_text

        # Écrit chaque file_name en mergeant avec l'existant (lock par fichier).
        for file_name, new_lines in by_file.items():
            with store.lock(file_name):
                existing = self._load_file(store, file_name) or {}
                merged = {**existing, **new_lines}
                store.write(file_name, self._adapter.dump_json(merged, indent=2))

    @override
    def load_for_chunk(
        self,
        chunk: ChunkProtocol,
        store: ByteStore,
        fallback: ByteStore | None = None,
    ) -> tuple[dict[int, str] | None, set[int]]:
        # Reconstruit la vue chunk-local (clés 0..N) depuis les fichiers
        # file-local du store (clés tag_key.index).
        chunk_lines: dict[int, str] = {}
        missing: set[int] = set()
        for chunk_idx, (page, tag_key, _) in enumerate(chunk.fetch_body()):
            file_name = str(page.epub_html.file_name)
            file_idx = int(tag_key.index)
            payload = self._load_file(store, file_name)
            value = payload.get(file_idx) if payload else None
            if value is None and fallback is not None:
                fb_payload = self._load_file(fallback, file_name)
                value = fb_payload.get(file_idx) if fb_payload else None
            if value is None:
                missing.add(chunk_idx)
            else:
                chunk_lines[chunk_idx] = value

        if not chunk_lines:
            return None, missing
        return chunk_lines, missing

    def _load_file(
        self, store: ByteStore | None, file_name: str
    ) -> dict[int, str] | None:
        """Charge le TypedDict file-local de `file_name`, `None` si absent / corrompu."""

        if store is None:
            return None
        raw = store.read(file_name)
        if raw is None:
            return None
        try:
            return self._adapter.validate_json(raw)
        except ValidationError as e:
            logger.warning(f"LineIndexedPersister: cache corrompu {file_name}: {e}")
            return None
