"""Tests `FileByteStore` + `MemoryByteStore` (couche bytes)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from ebook_translator.stores.byte_store import (
    ByteStore,
    FileByteStore,
    MemoryByteStore,
)


@pytest.fixture(params=["file", "memory"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> ByteStore:
    if request.param == "file":
        return FileByteStore(tmp_path / "cache")
    return MemoryByteStore()


class TestRoundtrip:
    def test_write_then_read(self, store: ByteStore) -> None:
        store.write("k1", b"hello")
        assert store.read("k1") == b"hello"

    def test_read_missing_returns_none(self, store: ByteStore) -> None:
        assert store.read("never") is None

    def test_write_overwrites(self, store: ByteStore) -> None:
        store.write("k", b"v1")
        store.write("k", b"v2")
        assert store.read("k") == b"v2"

    def test_binary_safe(self, store: ByteStore) -> None:
        payload = bytes(range(256))
        store.write("k", payload)
        assert store.read("k") == payload


class TestExistsDelete:
    def test_exists_false_before_write(self, store: ByteStore) -> None:
        assert store.exists("k") is False

    def test_exists_true_after_write(self, store: ByteStore) -> None:
        store.write("k", b"x")
        assert store.exists("k") is True

    def test_delete_removes(self, store: ByteStore) -> None:
        store.write("k", b"x")
        store.delete("k")
        assert store.exists("k") is False
        assert store.read("k") is None

    def test_delete_missing_is_noop(self, store: ByteStore) -> None:
        store.delete("never")  # ne lève pas


class TestListKeys:
    def test_list_keys_empty(self, store: ByteStore) -> None:
        assert list(store.list_keys()) == []

    def test_list_keys_after_writes(self, store: ByteStore) -> None:
        store.write("a", b"1")
        store.write("b", b"2")
        keys = list(store.list_keys())
        assert len(keys) == 2


class TestLock:
    def test_lock_serializes_writers(self, store: ByteStore) -> None:
        # Sans lock, deux writers concurrents écraseraient l'un l'autre.
        # Sous lock, le RMW (read-modify-write) du second observe l'écriture du premier.
        results: list[bytes] = []

        def rmw(token: bytes) -> None:
            with store.lock("shared"):
                current = store.read("shared") or b""
                store.write("shared", current + token)
                results.append(token)

        threads = [threading.Thread(target=rmw, args=(bytes([i]),)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final = store.read("shared")
        assert final is not None
        assert len(final) == 20  # toutes les contributions ont survécu

    def test_lock_reentrancy_not_required(self, store: ByteStore) -> None:
        # Le contrat n'exige pas la réentrance ; on vérifie juste qu'un
        # lock pris puis relâché peut être repris.
        with store.lock("k"):
            store.write("k", b"a")
        with store.lock("k"):
            store.write("k", b"b")
        assert store.read("k") == b"b"


class TestFileSpecific:
    def test_safe_filename_collision_resolution(self, tmp_path: Path) -> None:
        # "a/b" et "a_b" produisent le même safe_name mais des hashs distincts.
        store = FileByteStore(tmp_path / "cache")
        store.write("a/b", b"slash")
        store.write("a_b", b"underscore")
        assert store.read("a/b") == b"slash"
        assert store.read("a_b") == b"underscore"

    def test_creates_cache_dir(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "nested" / "cache"
        assert not target.exists()
        FileByteStore(target)
        assert target.exists()

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        s1 = FileByteStore(tmp_path / "cache")
        s1.write("k", b"persisted")
        s2 = FileByteStore(tmp_path / "cache")
        assert s2.read("k") == b"persisted"

    def test_concurrent_writes_no_partial_read(self, tmp_path: Path) -> None:
        # Atomicité : un lecteur n'observe jamais un fichier vide / partiel.
        store = FileByteStore(tmp_path / "cache")
        store.write("k", b"initial")
        observed: list[bytes | None] = []
        stop = threading.Event()

        def reader() -> None:
            while not stop.is_set():
                v = store.read("k")
                observed.append(v)

        def writer() -> None:
            for i in range(50):
                store.write("k", f"v{i}".encode() * 100)

        rt = threading.Thread(target=reader)
        wt = threading.Thread(target=writer)
        rt.start()
        wt.start()
        wt.join()
        stop.set()
        rt.join()

        # Aucune lecture ne doit renvoyer None (le fichier existe en
        # permanence) ni un contenu non-prefixé "initial" / "v\d+"
        for v in observed:
            assert v is not None
            assert v == b"initial" or v.startswith(b"v")
