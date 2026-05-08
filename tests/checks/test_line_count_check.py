"""Tests du nouveau `LineCountCheck` (Protocol `ContentCheck`)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ebook_translator.checks.content.line_count_check import LineCountCheck
from ebook_translator.validation.diagnostics import ErreursType
from template.phase.translation_models import LineIndexedTranslation


@dataclass(frozen=True)
class _FakeSource:
    indices: tuple[int, ...]

    @property
    def line_indices(self) -> Iterable[int]:
        return self.indices

    def text_at(self, index: int) -> str:
        if index not in self.indices:
            raise KeyError(index)
        return ""


def _payload(raw: str) -> LineIndexedTranslation:
    return LineIndexedTranslation.model_validate(raw)


class TestLineCountCheck:
    def test_error_type_is_class_level(self):
        assert LineCountCheck.error_type is ErreursType.LINES_MISSING

    def test_all_lines_present_returns_empty(self):
        check = LineCountCheck()
        payload = _payload("<0/>a\n<1/>b\n<2/>c\n[=[END]=]")
        source = _FakeSource(indices=(0, 1, 2))
        assert check.run(payload, source) == []

    def test_missing_lines_returns_one_aggregated_failure(self):
        check = LineCountCheck()
        payload = _payload("<0/>a\n<2/>c\n[=[END]=]")
        source = _FakeSource(indices=(0, 1, 2, 3))
        failures = check.run(payload, source)
        assert len(failures) == 1
        assert failures[0].error_type is ErreursType.LINES_MISSING
        assert failures[0].ctx["missing_indices"] == [1, 3]

    def test_missing_indices_are_sorted(self):
        check = LineCountCheck()
        payload = _payload("<5/>e\n[=[END]=]")
        source = _FakeSource(indices=(7, 2, 5, 0))
        failures = check.run(payload, source)
        assert len(failures) == 1
        assert failures[0].ctx["missing_indices"] == [0, 2, 7]

    def test_extra_lines_in_payload_do_not_raise(self):
        check = LineCountCheck()
        payload = _payload("<0/>a\n<1/>b\n<99/>extra\n[=[END]=]")
        source = _FakeSource(indices=(0, 1))
        assert check.run(payload, source) == []

    def test_failure_msg_mentions_counts(self):
        check = LineCountCheck()
        payload = _payload("<0/>a\n[=[END]=]")
        source = _FakeSource(indices=(0, 1, 2))
        failures = check.run(payload, source)
        assert len(failures) == 1
        assert "2" in failures[0].msg and "3" in failures[0].msg
