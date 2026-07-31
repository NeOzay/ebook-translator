"""Tests du routage worker ↔ phase dans `ValidationWorkerPool`.

Le choix du worker se fait sur `phase.content_checks` :

- phase avec checks → `UnifiedValidationWorker` (suppose du line-indexed) ;
- phase sans checks → `SchemaOnlyValidationWorker` (passe-plat).

Couvre aussi le recyclage des workers sur `switch_phase` quand les deux
phases n'ont pas le même type de worker.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import Mock

from ebook_translator.validation.schema_only_worker import SchemaOnlyValidationWorker
from ebook_translator.validation.unified_worker import UnifiedValidationWorker
from ebook_translator.validation.validation_queue import (
    SaveQueue,
    ValidationItem,
    ValidationQueue,
)
from ebook_translator.validation.validation_worker_pool import ValidationWorkerPool


@dataclass(frozen=True)
class _FakeChunk:
    index: int = 0


@dataclass
class _FakePhase:
    """Surface minimale lue par le pool et le worker passe-plat."""

    name: str = "fake"
    content_checks: tuple[Any, ...] = field(default_factory=tuple)


def _make_pool(phase: _FakePhase) -> ValidationWorkerPool:
    return ValidationWorkerPool(num_workers=2, phase=phase)  # type: ignore[arg-type]


def _make_item(data: Any) -> ValidationItem[Any]:
    return ValidationItem(
        chunk=_FakeChunk(),  # type: ignore[arg-type]
        chunk_info=Mock(),
        data=data,
    )


def _process(worker: SchemaOnlyValidationWorker, data: Any) -> Any:
    """Appelle le hook protégé du worker sur une donnée nue."""
    run = getattr(worker, "_process")  # noqa: B009
    return run(_make_item(data))


class TestWorkerSelection:
    def test_phase_sans_checks_route_vers_passe_plat(self) -> None:
        pool = _make_pool(_FakePhase(content_checks=()))

        assert len(pool.workers) == 2
        assert all(isinstance(w, SchemaOnlyValidationWorker) for w in pool.workers)

    def test_phase_avec_checks_route_vers_unified(self) -> None:
        pool = _make_pool(_FakePhase(content_checks=(Mock(),)))

        assert all(isinstance(w, UnifiedValidationWorker) for w in pool.workers)


class TestSchemaOnlyWorker:
    def test_data_traverse_sans_copie(self) -> None:
        """La donnée ressort **identique** — pas de `dict()` intermédiaire.

        Une phase à schéma seul peut porter une `list` ou un `BaseModel` ;
        toute copie line-indexed casserait la persistance.
        """
        worker = SchemaOnlyValidationWorker(
            validation_queue=ValidationQueue(),
            save_queue=SaveQueue(),
            phase=_FakePhase(),  # type: ignore[arg-type]
            stop_event=threading.Event(),
        )
        data = [{"terme": "Matrix", "proposition_traduction": "Matrice"}]

        assert _process(worker, data) is data

    def test_modele_pydantic_non_altere(self) -> None:
        worker = SchemaOnlyValidationWorker(
            validation_queue=ValidationQueue(),
            save_queue=SaveQueue(),
            phase=_FakePhase(),  # type: ignore[arg-type]
            stop_event=threading.Event(),
        )
        data = Mock()

        assert _process(worker, data) is data


class TestSwitchPhase:
    def test_meme_type_de_worker_conserve_les_instances(self) -> None:
        pool = _make_pool(_FakePhase(name="p1", content_checks=()))
        before = list(pool.workers)

        next_phase = _FakePhase(name="p2", content_checks=())
        pool.switch_phase(next_phase)  # type: ignore[arg-type]

        assert all(new is old for new, old in zip(pool.workers, before, strict=True))
        assert all(w.phase is next_phase for w in pool.workers)

    def test_type_different_recycle_les_workers(self) -> None:
        pool = _make_pool(_FakePhase(name="glossary", content_checks=()))
        before = list(pool.workers)

        next_phase = _FakePhase(name="initial", content_checks=(Mock(),))
        pool.switch_phase(next_phase)  # type: ignore[arg-type]

        assert all(isinstance(w, UnifiedValidationWorker) for w in pool.workers)
        assert all(all(w is not old for old in before) for w in pool.workers)
        assert all(w.phase is next_phase for w in pool.workers)

    def test_recyclage_conserve_les_queues(self) -> None:
        """Les workers changent, pas les queues — le `SaveWorker` continue."""
        pool = _make_pool(_FakePhase(content_checks=()))
        validation_queue = pool.validation_queue
        save_queue = pool.save_queue

        pool.switch_phase(_FakePhase(content_checks=(Mock(),)))  # type: ignore[arg-type]

        assert pool.validation_queue is validation_queue
        assert pool.save_queue is save_queue
        assert all(w.validation_queue is validation_queue for w in pool.workers)
        assert all(w.save_queue is save_queue for w in pool.workers)
