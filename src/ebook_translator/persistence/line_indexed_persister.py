"""Stratégie de persistance line-indexée (phases traduction).

Sémantique : un chunk produit un `LineIndexedTranslation` chunk-local
(`lines: dict[chunk_idx, translation]`). Cette stratégie projette ce
payload sur N fichiers `ByteStore` distincts (un par `file_name` HTML
traversé par le chunk), où chaque fichier stocke un
`LineIndexedTranslation` file-local (`lines: dict[file_idx, translation]`)
accumulant les contributions de **tous** les chunks ayant traversé ce
fichier source.

Projection chunk-local → file-local : pour chaque fragment du body,
`enumerate(chunk.fetch_body())` donne le chunk_idx (clé du payload
chunk-local) et `tag_key.index` donne le file_idx (clé du payload
file-local stocké).

Fallback : un `ByteStore` secondaire peut être consulté pour les indices
absents du store principal — utilisé pour le chaînage Phase 1 → Phase 2
(refinement lit Phase 1 si Phase 2 n'a pas encore caché la ligne).
"""

from __future__ import annotations

from pydantic import ValidationError

from ..logger import get_logger
from ..segmentation.chunk import ChunkProtocol
from ..stores.byte_store import ByteStore
from .chunk_persister import ChunkPersister

# Import retardé via TYPE_CHECKING serait sain, mais le persister doit
# instancier et lire `LineIndexedTranslation` à runtime. Garder import direct.
from template.phase.translation_models import LineIndexedTranslation

logger = get_logger(__name__)


class LineIndexedPersister(
    ChunkPersister[LineIndexedTranslation, ChunkProtocol]
):
    """Cache line-indexé : un fichier ByteStore par fichier source HTML."""

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
            if payload is None or file_idx not in payload.lines:
                return False
        return True

    def persist(
        self,
        chunk: ChunkProtocol,
        payload: LineIndexedTranslation,
        store: ByteStore,
    ) -> None:
        # Regroupe les lignes du payload chunk-local par file_name de destination,
        # en remappant chunk_idx → file_idx (= int(tag_key.index)).
        by_file: dict[str, dict[int, str]] = {}
        for chunk_idx, (page, tag_key, _) in enumerate(chunk.fetch_body()):
            line_text = payload.lines.get(chunk_idx)
            if line_text is None:
                # Le payload est partiel sur cet index : on ne caste pas
                # une ligne absente (un retry ciblé la fournira plus tard).
                continue
            file_name = str(page.epub_html.file_name)
            file_idx = int(tag_key.index)
            by_file.setdefault(file_name, {})[file_idx] = line_text

        # Écrit chaque file_name en mergeant avec l'existant (lock par fichier).
        for file_name, new_lines in by_file.items():
            with store.lock(file_name):
                existing = self._load_file(store, file_name)
                merged_lines: dict[int, str] = (
                    {**existing.lines, **new_lines} if existing else new_lines
                )
                merged = LineIndexedTranslation(lines=merged_lines)
                store.write(
                    file_name, merged.model_dump_json(indent=2).encode("utf-8")
                )

    def load_for_chunk(
        self,
        chunk: ChunkProtocol,
        store: ByteStore,
        fallback: ByteStore | None = None,
    ) -> tuple[LineIndexedTranslation | None, set[int]]:
        # Reconstruit la vue chunk-local (clés 0..N) depuis les fichiers
        # file-local du store (clés tag_key.index).
        chunk_lines: dict[int, str] = {}
        missing: set[int] = set()
        for chunk_idx, (page, tag_key, _) in enumerate(chunk.fetch_body()):
            file_name = str(page.epub_html.file_name)
            file_idx = int(tag_key.index)
            payload = self._load_file(store, file_name)
            value = payload.lines.get(file_idx) if payload else None
            if value is None and fallback is not None:
                fb_payload = self._load_file(fallback, file_name)
                value = fb_payload.lines.get(file_idx) if fb_payload else None
            if value is None:
                missing.add(chunk_idx)
            else:
                chunk_lines[chunk_idx] = value

        if not chunk_lines:
            return None, missing
        return LineIndexedTranslation(lines=chunk_lines), missing

    @staticmethod
    def _load_file(
        store: ByteStore | None, file_name: str
    ) -> LineIndexedTranslation | None:
        """Charge le payload file-local de `file_name`, `None` si absent / corrompu."""

        if store is None:
            return None
        raw = store.read(file_name)
        if raw is None:
            return None
        try:
            return LineIndexedTranslation.model_validate_json(raw)
        except ValidationError as e:
            logger.warning(f"LineIndexedPersister: cache corrompu {file_name}: {e}")
            return None
