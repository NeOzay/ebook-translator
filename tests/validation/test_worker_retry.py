"""Tests des helpers du worker unifié (Bloc B Step 4a).

Couvre `WorkerRetryContext`, `merge_data`, `lookup_strategy`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, ClassVar

import pytest

from ebook_translator.validation.diagnostics import ErreursType
from ebook_translator.validation.failure import ValidationFailure
from ebook_translator.validation.retry_strategy import RetryStrategy
from ebook_translator.validation.worker_retry import (
    WorkerRetryContext,
    is_instance_resolved,
    lookup_strategy,
    merge_data,
)

# ---------- WorkerRetryContext ----------


@dataclass(frozen=True)
class _FakeSource:
    texts: dict[int, str]

    @property
    def line_indices(self) -> Iterable[int]:
        return self.texts.keys()

    def text_at(self, index: int) -> str:
        return self.texts[index]


@dataclass(frozen=True)
class _FakeChunk:
    index: int = 0


class TestWorkerRetryContext:
    def test_satisfies_retry_context_protocol(self) -> None:
        ctx = WorkerRetryContext(
            target_language="fr",
            chunk=_FakeChunk(),  # type: ignore[arg-type]
            source=_FakeSource(texts={0: "x"}),
            current_data={0: "X"},
        )
        # Smoke: lecture des 4 attributs du Protocol
        assert ctx.target_language == "fr"
        assert ctx.chunk.index == 0
        assert ctx.source.text_at(0) == "x"
        assert ctx.current_data == {0: "X"}

    def test_frozen(self) -> None:
        ctx = WorkerRetryContext(
            target_language="fr",
            chunk=_FakeChunk(),  # type: ignore[arg-type]
            source=_FakeSource(texts={}),
            current_data={},
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            ctx.target_language = "en"  # type: ignore[misc]


# ---------- merge_data ----------


class TestMergeData:
    def test_replace_overwrites_prev_lines(self) -> None:
        prev = {0: "old0", 1: "keep1"}
        new = {0: "NEW0"}
        assert merge_data(prev, new, "replace") == {0: "NEW0", 1: "keep1"}

    def test_replace_adds_new_lines(self) -> None:
        prev = {0: "p0"}
        new = {1: "n1"}
        assert merge_data(prev, new, "replace") == {0: "p0", 1: "n1"}

    def test_merge_does_not_overwrite_prev(self) -> None:
        # mode merge : prev gagne sur collision (évite de casser des
        # lignes déjà validées avec des sorties retry partielles).
        prev = {0: "good0", 1: "good1"}
        new = {0: "BAD0", 2: "n2"}
        assert merge_data(prev, new, "merge") == {0: "good0", 1: "good1", 2: "n2"}

    def test_merge_fills_missing(self) -> None:
        prev = {0: "p0"}
        new = {1: "n1", 2: "n2"}
        assert merge_data(prev, new, "merge") == {0: "p0", 1: "n1", 2: "n2"}

    def test_empty_prev_replace(self) -> None:
        assert merge_data({}, {0: "x"}, "replace") == {0: "x"}

    def test_empty_new_merge(self) -> None:
        assert merge_data({0: "p"}, {}, "merge") == {0: "p"}


# ---------- lookup_strategy ----------


class _FakeContentCheck:
    """Stub minimal `ContentCheck` (juste les `ClassVar` métadonnées)."""

    def __init__(
        self,
        error_type: ErreursType,
        strategy: RetryStrategy,
        max_attempts: int,
    ) -> None:
        # On simule des ClassVar via attributs d'instance pour les tests
        self.error_type: ClassVar[ErreursType]  # type: ignore[misc]
        self.error_type = error_type  # type: ignore[misc]
        self.retry_strategy: ClassVar[RetryStrategy]  # type: ignore[misc]
        self.retry_strategy = strategy  # type: ignore[misc]
        self.max_attempts: ClassVar[int]  # type: ignore[misc]
        self.max_attempts = max_attempts  # type: ignore[misc]

    def run(self, data: Any, source: Any) -> list[ValidationFailure[Any]]:
        return []


class TestLookupStrategy:
    def test_schema_level_error_returns_schema_constants(self) -> None:
        from ebook_translator.llm.retry_registry import (
            SCHEMA_MAX_ATTEMPTS,
            SCHEMA_RETRY_STRATEGY,
        )

        failure = ValidationFailure[Any](
            error_type=ErreursType.OUTPUT_FORMAT_INVALID,
            msg="bad format",
            ctx={},
        )
        strategy, max_attempts = lookup_strategy(failure, content_checks=())
        assert strategy == SCHEMA_RETRY_STRATEGY
        assert max_attempts == SCHEMA_MAX_ATTEMPTS

    def test_content_level_error_uses_check_metadata(self) -> None:
        check = _FakeContentCheck(
            error_type=ErreursType.LINES_MISSING,
            strategy=RetryStrategy.NORMAL_ONLY,
            max_attempts=3,
        )
        failure = ValidationFailure[Any](
            error_type=ErreursType.LINES_MISSING,
            msg="missing",
            ctx={"missing_indices": [1]},
        )
        strategy, max_attempts = lookup_strategy(failure, content_checks=(check,))  # type: ignore[arg-type]
        assert strategy == RetryStrategy.NORMAL_ONLY
        assert max_attempts == 3

    def test_picks_correct_check_among_many(self) -> None:
        c1 = _FakeContentCheck(ErreursType.LINES_MISSING, RetryStrategy.NORMAL_ONLY, 2)
        c2 = _FakeContentCheck(
            ErreursType.FRAGMENT_COUNT_MISMATCH,
            RetryStrategy.PROGRESSIVE_REASONING,
            5,
        )
        failure = ValidationFailure[Any](
            error_type=ErreursType.FRAGMENT_COUNT_MISMATCH,
            msg="frag",
            ctx={"line": 0, "expected_pairs": 1, "actual_pairs": 0},
        )
        strategy, max_attempts = lookup_strategy(failure, content_checks=(c1, c2))  # type: ignore[arg-type]
        assert strategy == RetryStrategy.PROGRESSIVE_REASONING
        assert max_attempts == 5

    def test_unknown_error_raises_keyerror(self) -> None:
        # Sentence_invalid sans check correspondant et hors SCHEMA_LEVEL_ERRORS
        failure = ValidationFailure[Any](
            error_type=ErreursType.SENTENCE_INVALID,
            msg="x",
            ctx={"invalid_indices": [0]},
        )
        with pytest.raises(KeyError, match="Aucune politique"):
            lookup_strategy(failure, content_checks=())


# ---------- is_instance_resolved ----------


class TestIsInstanceResolved:
    def test_replace_resolved_when_line_absent(self) -> None:
        prev = ValidationFailure[Any](
            error_type=ErreursType.FRAGMENT_COUNT_MISMATCH,
            msg="",
            ctx={"line": 3, "expected_pairs": 1, "actual_pairs": 0},
        )
        # Failure courante sur une AUTRE ligne du même type : résolu pour ligne 3.
        other = ValidationFailure[Any](
            error_type=ErreursType.FRAGMENT_COUNT_MISMATCH,
            msg="",
            ctx={"line": 5, "expected_pairs": 1, "actual_pairs": 0},
        )
        assert is_instance_resolved(prev, [other], "replace") is True

    def test_replace_unresolved_when_same_line_persists(self) -> None:
        prev = ValidationFailure[Any](
            error_type=ErreursType.FRAGMENT_COUNT_MISMATCH,
            msg="",
            ctx={"line": 3, "expected_pairs": 1, "actual_pairs": 0},
        )
        same = ValidationFailure[Any](
            error_type=ErreursType.FRAGMENT_COUNT_MISMATCH,
            msg="",
            ctx={"line": 3, "expected_pairs": 1, "actual_pairs": 0},
        )
        assert is_instance_resolved(prev, [same], "replace") is False

    def test_merge_resolved_when_no_failure_of_type(self) -> None:
        prev = ValidationFailure[Any](
            error_type=ErreursType.LINES_MISSING,
            msg="",
            ctx={"missing_indices": [3, 5]},
        )
        assert is_instance_resolved(prev, [], "merge") is True

    def test_merge_unresolved_even_with_shrunk_batch(self) -> None:
        prev = ValidationFailure[Any](
            error_type=ErreursType.LINES_MISSING,
            msg="",
            ctx={"missing_indices": [3, 5]},
        )
        # Batch rétréci à [5] → toujours la même instance pour `merge`.
        shrunk = ValidationFailure[Any](
            error_type=ErreursType.LINES_MISSING,
            msg="",
            ctx={"missing_indices": [5]},
        )
        assert is_instance_resolved(prev, [shrunk], "merge") is False
