"""Tests `MemoizedChunkPersister[M]`."""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel

from ebook_translator.persistence.memoized_chunk_persister import (
    MemoizedChunkPersister,
)
from ebook_translator.stores.byte_store import MemoryByteStore


class _Sample(BaseModel):
    value: str


@dataclass
class _FakeChunk:
    outer_key: str
    inner_key: str


def _persister() -> MemoizedChunkPersister[_Sample]:
    return MemoizedChunkPersister(_Sample)


# ---------- is_chunk_cached / persist / load_for_chunk ----------


class TestRoundtrip:
    def test_is_cached_false_before_persist(self) -> None:
        p = _persister()
        store = MemoryByteStore()
        chunk = _FakeChunk("ch1", "fp_a")
        assert p.is_chunk_cached(chunk, store) is False

    def test_is_cached_true_after_persist(self) -> None:
        p = _persister()
        store = MemoryByteStore()
        chunk = _FakeChunk("ch1", "fp_a")
        p.persist(chunk, _Sample(value="x"), store)
        assert p.is_chunk_cached(chunk, store) is True

    def test_load_for_chunk_returns_payload(self) -> None:
        p = _persister()
        store = MemoryByteStore()
        chunk = _FakeChunk("ch1", "fp_a")
        p.persist(chunk, _Sample(value="payload"), store)

        loaded, missing = p.load_for_chunk(chunk, store)
        assert loaded is not None
        assert loaded.value == "payload"
        assert missing == set()

    def test_load_for_chunk_missing(self) -> None:
        p = _persister()
        store = MemoryByteStore()
        chunk = _FakeChunk("ch1", "fp_absent")
        loaded, missing = p.load_for_chunk(chunk, store)
        assert loaded is None
        assert missing == {"fp_absent"}


# ---------- isolation outer / inner ----------


class TestIsolation:
    def test_inner_keys_isolated_per_outer(self) -> None:
        p = _persister()
        store = MemoryByteStore()
        p.persist(_FakeChunk("ch1", "shared"), _Sample(value="ch1"), store)
        # même inner_key sur un autre outer ne doit pas matcher
        assert p.is_chunk_cached(_FakeChunk("ch2", "shared"), store) is False

    def test_multiple_inner_keys_coexist(self) -> None:
        p = _persister()
        store = MemoryByteStore()
        p.persist(_FakeChunk("ch1", "fp_a"), _Sample(value="A"), store)
        p.persist(_FakeChunk("ch1", "fp_b"), _Sample(value="B"), store)
        p.persist(_FakeChunk("ch1", "fp_c"), _Sample(value="C"), store)

        all_entries = p.all_for_outer("ch1", store)
        assert {k: v.value for k, v in all_entries.items()} == {
            "fp_a": "A",
            "fp_b": "B",
            "fp_c": "C",
        }

    def test_persist_on_one_inner_does_not_affect_others(self) -> None:
        p = _persister()
        store = MemoryByteStore()
        p.persist(_FakeChunk("ch1", "fp_a"), _Sample(value="A"), store)
        p.persist(_FakeChunk("ch1", "fp_b"), _Sample(value="B"), store)

        loaded_a, _ = p.load_for_chunk(_FakeChunk("ch1", "fp_a"), store)
        loaded_b, _ = p.load_for_chunk(_FakeChunk("ch1", "fp_b"), store)
        assert loaded_a is not None and loaded_a.value == "A"
        assert loaded_b is not None and loaded_b.value == "B"


# ---------- overwrite ----------


class TestOverwrite:
    def test_persist_same_inner_overwrites(self) -> None:
        p = _persister()
        store = MemoryByteStore()
        chunk = _FakeChunk("ch1", "fp")
        p.persist(chunk, _Sample(value="old"), store)
        p.persist(chunk, _Sample(value="new"), store)

        loaded, _ = p.load_for_chunk(chunk, store)
        assert loaded is not None and loaded.value == "new"


# ---------- format disque legacy-compat ----------


class TestLegacyFormat:
    def test_writes_dict_of_json_strings(self) -> None:
        p = _persister()
        store = MemoryByteStore()
        p.persist(_FakeChunk("ch1", "fp"), _Sample(value="x"), store)

        raw = store.read("ch1")
        assert raw is not None
        outer = json.loads(raw)
        assert isinstance(outer, dict)
        # valeur = string JSON imbriquée (compat legacy Store)
        assert isinstance(outer["fp"], str)
        inner = json.loads(outer["fp"])
        assert inner == {"value": "x"}

    def test_reads_pre_existing_legacy_payload(self) -> None:
        p = _persister()
        store = MemoryByteStore()
        # Simule un cache legacy posé par l'ancien Store
        legacy_inner = _Sample(value="legacy").model_dump_json()
        legacy_outer = {"fp_legacy": legacy_inner}
        store.write("ch1", json.dumps(legacy_outer).encode())

        loaded, missing = p.load_for_chunk(_FakeChunk("ch1", "fp_legacy"), store)
        assert loaded is not None
        assert loaded.value == "legacy"
        assert missing == set()


# ---------- robustesse ----------


class TestCorruption:
    def test_corrupt_outer_treated_as_empty(self) -> None:
        p = _persister()
        store = MemoryByteStore()
        store.write("ch1", b"not json")
        chunk = _FakeChunk("ch1", "fp")
        assert p.is_chunk_cached(chunk, store) is False

        loaded, missing = p.load_for_chunk(chunk, store)
        assert loaded is None
        assert missing == {"fp"}

    def test_corrupt_inner_value_silently_skipped_in_all(self) -> None:
        p = _persister()
        store = MemoryByteStore()
        # Pose un dict valide avec une entrée saine + une entrée invalide.
        good = _Sample(value="ok").model_dump_json()
        outer = {"good": good, "bad": '{"oops": "no value field"}'}
        store.write("ch1", json.dumps(outer).encode())

        all_entries = p.all_for_outer("ch1", store)
        # Seul `good` survit ; `bad` est silencieusement ignoré.
        assert set(all_entries.keys()) == {"good"}
        assert all_entries["good"].value == "ok"

    def test_outer_non_dict_treated_as_empty(self) -> None:
        p = _persister()
        store = MemoryByteStore()
        store.write("ch1", b'["not", "a", "dict"]')
        assert p.all_for_outer("ch1", store) == {}
