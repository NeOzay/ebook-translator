"""Tests `LineIndexedPersister`.

Utilise des fakes minimaux pour éviter de monter un vrai EPUB :
seules les surfaces touchées par le persister sont mockées
(`chunk.fetch_body()`, `page.epub_html.file_name`, `tag_key.index`).

Format disque attendu : TypedDict pur `{"<file_idx>": "<text>"}` (pas
de wrapper `{"lines": ...}` Pydantic).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from ebook_translator.persistence.line_indexed_persister import LineIndexedPersister
from ebook_translator.stores.byte_store import MemoryByteStore
from template.phase.translation_models import LineIndexedLLMResponse

_ADAPTER = LineIndexedLLMResponse.target_adapter()


# ---------- Fakes ----------


@dataclass
class _FakeEpub:
    file_name: str


@dataclass
class _FakePage:
    epub_html: _FakeEpub


@dataclass
class _FakeTagKey:
    index: str  # comme TagKey.index (str)
    page: _FakePage


@dataclass
class _FakeChunk:
    """Surface minimale satisfaisant les usages du persister via duck-typing."""

    body: list[_FakeTagKey] = field(default_factory=list)

    def fetch_body(self) -> Iterator[tuple[Any, Any, str]]:
        for tk in self.body:
            yield tk.page, tk, ""

    # Champs requis par ChunkProtocol mais inutilisés ici.
    index: int = 0


def _make_chunk(*frags: tuple[str, int]) -> _FakeChunk:
    """Construit un chunk depuis `(file_name, file_idx)` triples."""

    return _FakeChunk(
        body=[
            _FakeTagKey(
                index=str(idx), page=_FakePage(epub_html=_FakeEpub(file_name=fn))
            )
            for fn, idx in frags
        ]
    )


def _serialize(d: dict[int, str]) -> bytes:
    return _ADAPTER.dump_json(d)


def _load(raw: bytes | None) -> dict[int, str]:
    assert raw is not None
    return _ADAPTER.validate_json(raw)


# ---------- is_chunk_cached ----------


class TestIsChunkCached:
    def test_returns_false_when_store_empty(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        chunk = _make_chunk(("a.html", 0), ("a.html", 1))
        assert p.is_chunk_cached(chunk, MemoryByteStore()) is False  # type: ignore[arg-type]

    def test_returns_true_when_all_indices_present_single_file(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        store = MemoryByteStore()
        store.write("a.html", _serialize({0: "t0", 1: "t1"}))
        chunk = _make_chunk(("a.html", 0), ("a.html", 1))
        assert p.is_chunk_cached(chunk, store) is True  # type: ignore[arg-type]

    def test_returns_false_when_one_index_missing(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        store = MemoryByteStore()
        store.write("a.html", _serialize({0: "t0"}))
        chunk = _make_chunk(("a.html", 0), ("a.html", 1))
        assert p.is_chunk_cached(chunk, store) is False  # type: ignore[arg-type]

    def test_returns_true_when_chunk_spans_multiple_files(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        store = MemoryByteStore()
        store.write("a.html", _serialize({0: "a0"}))
        store.write("b.html", _serialize({3: "b3"}))
        chunk = _make_chunk(("a.html", 0), ("b.html", 3))
        assert p.is_chunk_cached(chunk, store) is True  # type: ignore[arg-type]

    def test_fallback_covers_missing_when_main_empty(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        main = MemoryByteStore()
        fallback = MemoryByteStore()
        fallback.write("a.html", _serialize({0: "fb0", 1: "fb1"}))
        chunk = _make_chunk(("a.html", 0), ("a.html", 1))
        assert p.is_chunk_cached(chunk, main, fallback) is True  # type: ignore[arg-type]

    def test_fallback_partial_still_returns_false(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        main = MemoryByteStore()
        fallback = MemoryByteStore()
        fallback.write("a.html", _serialize({0: "fb0"}))
        chunk = _make_chunk(("a.html", 0), ("a.html", 1))
        assert p.is_chunk_cached(chunk, main, fallback) is False  # type: ignore[arg-type]


# ---------- persist ----------


class TestPersist:
    def test_writes_single_file(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        store = MemoryByteStore()
        chunk = _make_chunk(("a.html", 0), ("a.html", 1))
        # payload chunk-local : lignes 0..1
        p.persist(chunk, {0: "T0", 1: "T1"}, store)  # type: ignore[arg-type]

        # file-local : indices = tag_key.index
        assert _load(store.read("a.html")) == {0: "T0", 1: "T1"}

    def test_writes_remap_chunk_idx_to_file_idx(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        store = MemoryByteStore()
        # tag_key.index = 5 et 7 (file-local) ; chunk_idx = 0 et 1
        chunk = _make_chunk(("a.html", 5), ("a.html", 7))
        p.persist(chunk, {0: "T0", 1: "T1"}, store)  # type: ignore[arg-type]

        assert _load(store.read("a.html")) == {5: "T0", 7: "T1"}

    def test_writes_split_across_files(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        store = MemoryByteStore()
        chunk = _make_chunk(("a.html", 0), ("b.html", 3), ("a.html", 1))
        p.persist(chunk, {0: "Ta0", 1: "Tb3", 2: "Ta1"}, store)  # type: ignore[arg-type]

        assert _load(store.read("a.html")) == {0: "Ta0", 1: "Ta1"}
        assert _load(store.read("b.html")) == {3: "Tb3"}

    def test_merges_with_existing_payload(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        store = MemoryByteStore()
        # Pré-existant : un autre chunk a déjà déposé ses lignes
        store.write("a.html", _serialize({4: "old4"}))

        chunk = _make_chunk(("a.html", 0), ("a.html", 1))
        p.persist(chunk, {0: "T0", 1: "T1"}, store)  # type: ignore[arg-type]

        # Existant préservé + nouvelles lignes ajoutées
        assert _load(store.read("a.html")) == {0: "T0", 1: "T1", 4: "old4"}

    def test_merge_overwrites_on_collision(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        store = MemoryByteStore()
        store.write("a.html", _serialize({0: "old0"}))

        chunk = _make_chunk(("a.html", 0))
        p.persist(chunk, {0: "NEW0"}, store)  # type: ignore[arg-type]

        # Le nouveau écrase l'ancien sur un index commun.
        assert _load(store.read("a.html")) == {0: "NEW0"}

    def test_partial_payload_skips_missing_chunk_idx(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        store = MemoryByteStore()
        chunk = _make_chunk(("a.html", 0), ("a.html", 1), ("a.html", 2))
        # Payload chunk-local incomplet : pas de chunk_idx=1
        p.persist(chunk, {0: "T0", 2: "T2"}, store)  # type: ignore[arg-type]

        # Seuls les indices fournis sont écrits ; le file_idx 1 absent.
        assert _load(store.read("a.html")) == {0: "T0", 2: "T2"}


# ---------- load_for_chunk ----------


class TestLoadForChunk:
    def test_returns_none_and_all_missing_when_store_empty(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        chunk = _make_chunk(("a.html", 0), ("a.html", 1))
        payload, missing = p.load_for_chunk(chunk, MemoryByteStore())  # type: ignore[arg-type]
        assert payload is None
        assert missing == {0, 1}

    def test_reconstructs_chunk_local_view(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        store = MemoryByteStore()
        # File-local : indices 5, 7
        store.write("a.html", _serialize({5: "Ta5", 7: "Ta7"}))
        chunk = _make_chunk(("a.html", 5), ("a.html", 7))
        payload, missing = p.load_for_chunk(chunk, store)  # type: ignore[arg-type]

        # Chunk-local : indices 0, 1
        assert payload == {0: "Ta5", 1: "Ta7"}
        assert missing == set()

    def test_partial_load_marks_missing_chunk_idx(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        store = MemoryByteStore()
        store.write("a.html", _serialize({0: "Ta0"}))
        chunk = _make_chunk(("a.html", 0), ("a.html", 1))
        payload, missing = p.load_for_chunk(chunk, store)  # type: ignore[arg-type]

        assert payload == {0: "Ta0"}
        assert missing == {1}

    def test_fallback_fills_gaps(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        main = MemoryByteStore()
        fallback = MemoryByteStore()
        main.write("a.html", _serialize({0: "M0"}))
        fallback.write("a.html", _serialize({1: "F1"}))
        chunk = _make_chunk(("a.html", 0), ("a.html", 1))

        payload, missing = p.load_for_chunk(chunk, main, fallback)  # type: ignore[arg-type]
        assert payload == {0: "M0", 1: "F1"}
        assert missing == set()

    def test_main_takes_precedence_over_fallback(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        main = MemoryByteStore()
        fallback = MemoryByteStore()
        main.write("a.html", _serialize({0: "M0"}))
        fallback.write("a.html", _serialize({0: "F0"}))
        chunk = _make_chunk(("a.html", 0))

        payload, missing = p.load_for_chunk(chunk, main, fallback)  # type: ignore[arg-type]
        assert payload == {0: "M0"}
        assert missing == set()


# ---------- corruption / robustesse ----------


class TestCorruption:
    def test_corrupt_file_treated_as_absent(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        store = MemoryByteStore()
        store.write("a.html", b"not a valid json")
        chunk = _make_chunk(("a.html", 0))
        assert p.is_chunk_cached(chunk, store) is False  # type: ignore[arg-type]

        payload, missing = p.load_for_chunk(chunk, store)  # type: ignore[arg-type]
        assert payload is None
        assert missing == {0}

    def test_persist_overwrites_corrupt_file(self) -> None:
        p = LineIndexedPersister(LineIndexedLLMResponse)
        store = MemoryByteStore()
        store.write("a.html", b"corruption")
        chunk = _make_chunk(("a.html", 0))
        p.persist(chunk, {0: "T0"}, store)  # type: ignore[arg-type]

        # Le fichier corrompu a été ignoré par le merge → écrit à nouveau proprement.
        assert _load(store.read("a.html")) == {0: "T0"}

    def test_legacy_pydantic_format_treated_as_absent(self) -> None:
        """Format legacy `{"lines": {...}}` ≠ TypedDict pur `{...}`.

        Doit être traité comme corrompu (pas de migration silencieuse).
        """
        p = LineIndexedPersister(LineIndexedLLMResponse)
        store = MemoryByteStore()
        store.write("a.html", json.dumps({"lines": {"0": "old"}}).encode())
        chunk = _make_chunk(("a.html", 0))
        payload, missing = p.load_for_chunk(chunk, store)  # type: ignore[arg-type]
        assert payload is None
        assert missing == {0}
