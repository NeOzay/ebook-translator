"""Tests d'intégration : phases traduction × `PhaseStorage` (Bloc A).

Instancie `InitialTranslationPhase` / `RefinementPhase` avec un contexte
minimal (juste `store_manager` mockée) et vérifie que :
- `persist_chunk(chunk, data)` écrit via `PhaseStorage.persist`
- `load_chunk_view(chunk)` reconstruit la même donnée
- `get_translation_cache(chunk)` retourne `(TD, missing) | None`
- `save_item_builder(chunk, data)` retourne un `SaveItem` self-contained
  avec `persister` + `byte_store`
- `RefinementPhase` consulte Phase 1 via `get_byte_fallback_store`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ebook_translator.pipeline.phases.initial_translation import InitialTranslationPhase
from ebook_translator.pipeline.phases.refinement import RefinementPhase
from ebook_translator.stores.byte_store import FileByteStore
from template.phase.translation_models import LineIndexedLLMResponse

_ADAPTER = LineIndexedLLMResponse.target_adapter()


# ---------- Fakes pour les chunks ----------


@dataclass
class _FakeEpub:
    file_name: str


@dataclass
class _FakePage:
    epub_html: _FakeEpub


@dataclass
class _FakeTagKey:
    index: str
    page: _FakePage


@dataclass
class _FakeChunk:
    body: list[_FakeTagKey] = field(default_factory=list)
    index: int = 0

    def fetch_body(self) -> Any:
        for tk in self.body:
            yield tk.page, tk, ""


def _make_chunk(*frags: tuple[str, int]) -> _FakeChunk:
    return _FakeChunk(
        body=[
            _FakeTagKey(index=str(idx), page=_FakePage(_FakeEpub(file_name=fn)))
            for fn, idx in frags
        ]
    )


# ---------- Setup phase avec context minimal ----------


def _setup_phase(
    phase_cls: type[InitialTranslationPhase] | type[RefinementPhase],
    cache_dir: Path,
    fallback_dir: Path | None = None,
) -> Any:
    """Instancie la phase et lui pose un context mock avec store_manager."""

    phase = phase_cls(max_tokens=100)
    ctx = MagicMock()
    main_store = MagicMock()
    main_store.cache_dir = cache_dir

    def get_store(key: Any) -> MagicMock:
        if fallback_dir is not None and "initial" in str(key):
            fb = MagicMock()
            fb.cache_dir = fallback_dir
            return fb
        return main_store

    ctx.store_manager.get_store.side_effect = get_store
    phase.context = ctx
    # Tests de persistance — désactiver les content_checks (validation cache)
    # qui consommeraient des sources textuelles que les fakes ne fournissent pas.
    phase.content_checks = ()
    return phase


def _read_byte_store(cache_dir: Path, subdir: str, file_name: str) -> dict[int, str]:
    bs = FileByteStore(cache_dir / subdir)
    raw = bs.read(file_name)
    assert raw is not None
    return _ADAPTER.validate_json(raw)


# ---------- InitialTranslationPhase ----------


class TestInitialTranslationPersistence:
    def test_persist_chunk_writes_via_byte_store(self, tmp_path: Path) -> None:
        phase = _setup_phase(InitialTranslationPhase, tmp_path / "initial")
        chunk = _make_chunk(("a.html", 0), ("a.html", 1))

        phase.persist_chunk(chunk, {0: "T0", 1: "T1"})

        assert _read_byte_store(
            tmp_path / "initial", phase.BYTE_STORE_SUBDIR, "a.html"
        ) == {0: "T0", 1: "T1"}

    def test_load_chunk_view_roundtrip(self, tmp_path: Path) -> None:
        phase = _setup_phase(InitialTranslationPhase, tmp_path / "initial")
        chunk = _make_chunk(("a.html", 5), ("a.html", 7))

        phase.persist_chunk(chunk, {0: "T0", 1: "T1"})

        loaded, missing = phase.load_chunk_view(chunk)
        assert loaded == {0: "T0", 1: "T1"}
        assert missing == set()

    def test_get_translation_cache_full(self, tmp_path: Path) -> None:
        phase = _setup_phase(InitialTranslationPhase, tmp_path / "initial")
        chunk = _make_chunk(("a.html", 0), ("a.html", 1))
        phase.persist_chunk(chunk, {0: "T0", 1: "T1"})

        result = phase.get_translation_cache(chunk)
        assert result is not None
        data, missing = result
        assert data == {0: "T0", 1: "T1"}
        assert missing == set()

    def test_get_translation_cache_empty_returns_none(self, tmp_path: Path) -> None:
        phase = _setup_phase(InitialTranslationPhase, tmp_path / "initial")
        chunk = _make_chunk(("a.html", 0))

        assert phase.get_translation_cache(chunk) is None

    def test_save_item_is_self_contained(self, tmp_path: Path) -> None:
        phase = _setup_phase(InitialTranslationPhase, tmp_path / "initial")
        chunk = _make_chunk(("a.html", 0), ("a.html", 1))

        item = phase.save_item_builder(chunk, {0: "T0", 1: "T1"})
        # SaveItem porte tout le contexte nécessaire à SaveWorker
        assert item.persister is phase.persister
        assert item.byte_store is phase.storage.byte_store
        assert item.data == {0: "T0", 1: "T1"}

        # Invocation directe : le SaveItem peut se persister seul
        item.persister.persist(item.chunk, item.data, item.byte_store)
        assert _read_byte_store(
            tmp_path / "initial", phase.BYTE_STORE_SUBDIR, "a.html"
        ) == {0: "T0", 1: "T1"}


# ---------- RefinementPhase + fallback Phase 1 ----------


class TestRefinementPersistence:
    @pytest.fixture
    def both_dirs(self, tmp_path: Path) -> tuple[Path, Path]:
        return tmp_path / "initial", tmp_path / "refinement"

    def test_fallback_reads_phase1_data(self, both_dirs: tuple[Path, Path]) -> None:
        initial_dir, refinement_dir = both_dirs
        phase1 = _setup_phase(InitialTranslationPhase, initial_dir)
        chunk_p1 = _make_chunk(("a.html", 0), ("a.html", 1))
        phase1.persist_chunk(chunk_p1, {0: "P1_T0", 1: "P1_T1"})

        phase2 = _setup_phase(RefinementPhase, refinement_dir, fallback_dir=initial_dir)

        chunk_p2 = _make_chunk(("a.html", 0), ("a.html", 1))
        loaded, missing = phase2.load_chunk_view(chunk_p2)
        assert loaded == {0: "P1_T0", 1: "P1_T1"}
        assert missing == set()

    def test_phase2_writes_take_precedence_over_fallback(
        self, both_dirs: tuple[Path, Path]
    ) -> None:
        initial_dir, refinement_dir = both_dirs
        phase1 = _setup_phase(InitialTranslationPhase, initial_dir)
        phase1.persist_chunk(_make_chunk(("a.html", 0)), {0: "P1_TXT"})

        phase2 = _setup_phase(RefinementPhase, refinement_dir, fallback_dir=initial_dir)
        phase2.persist_chunk(_make_chunk(("a.html", 0)), {0: "P2_TXT"})

        loaded, _ = phase2.load_chunk_view(_make_chunk(("a.html", 0)))
        assert loaded == {0: "P2_TXT"}
