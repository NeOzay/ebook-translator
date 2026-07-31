"""Tests `SaveWorker` — `SaveItem` self-contained (Bloc A).

Vérifie que le worker délègue intégralement à `item.persister.persist(
chunk, data, byte_store)` et reste agnostique du persister concret.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from ebook_translator.validation.save_worker import SaveWorker
from ebook_translator.validation.validation_queue import SaveItem, SaveQueue


@dataclass
class _FakeChunk:
    index: int = 0


def _make_item(
    persister: Any,
    *,
    data: dict[int, str] | None = None,
    on_save: Any = None,
) -> SaveItem:
    return SaveItem(
        chunk=_FakeChunk(),  # type: ignore[arg-type]
        data=data or {0: "x"},
        persister=persister,
        byte_store=MagicMock(),
        on_save=on_save,
    )


def _start_worker(
    queue_size: int = 10,
) -> tuple[SaveWorker, SaveQueue, threading.Event, threading.Thread]:
    save_queue = SaveQueue(maxsize=queue_size)
    stop = threading.Event()
    worker = SaveWorker(save_queue=save_queue, stop_event=stop)
    thread = threading.Thread(target=worker.run, daemon=True)
    thread.start()
    return worker, save_queue, stop, thread


def _wait_until(predicate: Any, timeout_s: float = 2.0) -> None:
    deadline = threading.Event()
    for _ in range(int(timeout_s / 0.02)):
        if predicate():
            return
        deadline.wait(0.02)


def _shutdown(stop: threading.Event, thread: threading.Thread) -> None:
    stop.set()
    thread.join(timeout=2.0)


class TestSaveItemPath:
    def test_persister_persist_called(self) -> None:
        worker, sq, stop, thread = _start_worker()
        try:
            persister = MagicMock()
            sq.put(_make_item(persister))

            _wait_until(lambda: worker.saved_count >= 1)

            assert worker.saved_count == 1
            persister.persist.assert_called_once()
            args, _ = persister.persist.call_args
            assert args[1] == {0: "x"}  # data passed through
        finally:
            _shutdown(stop, thread)

    def test_exception_increments_error_count(self) -> None:
        worker, sq, stop, thread = _start_worker()
        try:
            persister = MagicMock()
            persister.persist.side_effect = RuntimeError("disk full")
            sq.put(_make_item(persister))

            _wait_until(lambda: worker.error_count >= 1)

            assert worker.error_count == 1
            assert worker.saved_count == 0
        finally:
            _shutdown(stop, thread)

    def test_on_save_callback_fires(self) -> None:
        worker, sq, stop, thread = _start_worker()
        try:
            received: list[tuple[Any, Any]] = []

            def record(chunk: Any, data: Any) -> None:
                received.append((chunk, data))

            sq.put(_make_item(MagicMock(), on_save=record))

            _wait_until(lambda: worker.saved_count >= 1)

            assert worker.saved_count == 1
            assert len(received) == 1
            chunk, data = received[0]
            assert isinstance(chunk, _FakeChunk)
            assert data == {0: "x"}
        finally:
            _shutdown(stop, thread)

    def test_on_save_failure_does_not_crash_worker(self) -> None:
        worker, sq, stop, thread = _start_worker()
        try:

            def boom(_chunk: Any, _data: Any) -> None:
                raise ValueError("callback fail")

            sq.put(_make_item(MagicMock(), on_save=boom))

            _wait_until(lambda: worker.saved_count >= 1)

            # Sauvegarde réussie ; callback en erreur logué mais non bloquant.
            assert worker.saved_count == 1
            assert worker.error_count == 0
        finally:
            _shutdown(stop, thread)
