"""Tests du nouveau `FragmentCountCheck`."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ebook_translator.checks.content.fragment_count_check import FragmentCountCheck
from ebook_translator.validation.diagnostics import ErreursType
from template.phase.translation_models import LineIndexedTranslation


@dataclass(frozen=True)
class _FakeSource:
    texts: dict[int, str]

    @property
    def line_indices(self) -> Iterable[int]:
        return self.texts.keys()

    def text_at(self, index: int) -> str:
        return self.texts[index]


def _payload(raw: str) -> dict[int, str]:
    return LineIndexedTranslation.model_validate(raw).build()


class TestFragmentCountCheck:
    def test_error_type_is_class_level(self):
        assert FragmentCountCheck.error_type is ErreursType.FRAGMENT_COUNT_MISMATCH

    def test_matching_separators_returns_empty(self):
        check = FragmentCountCheck()
        payload = _payload("<0/>a</>b\n<1/>c</>d</>e\n[=[END]=]")
        source = _FakeSource(texts={0: "x</>y", 1: "p</>q</>r"})
        assert check.run(payload, source) == []

    def test_no_separators_anywhere(self):
        check = FragmentCountCheck()
        payload = _payload("<0/>a\n<1/>b\n[=[END]=]")
        source = _FakeSource(texts={0: "x", 1: "y"})
        assert check.run(payload, source) == []

    def test_one_failure_per_offending_line(self):
        check = FragmentCountCheck()
        payload = _payload("<0/>a</>b\n<1/>cd\n<2/>e</>f\n<3/>g\n[=[END]=]")
        source = _FakeSource(texts={0: "x</>y", 1: "p</>q", 2: "r</>s", 3: "u</>v"})
        failures = check.run(payload, source)
        assert len(failures) == 2
        # Lignes 1 et 3 fautives.
        offending = sorted(f.ctx["line"] for f in failures)
        assert offending == [1, 3]
        for failure in failures:
            assert failure.error_type is ErreursType.FRAGMENT_COUNT_MISMATCH

    def test_extra_separator_detected(self):
        check = FragmentCountCheck()
        payload = _payload("<0/>a</>b</>c\n[=[END]=]")
        source = _FakeSource(texts={0: "x</>y"})
        failures = check.run(payload, source)
        assert len(failures) == 1
        assert failures[0].ctx["expected_pairs"] == 1
        assert failures[0].ctx["actual_pairs"] == 2

    def test_missing_index_in_payload_skipped(self):
        check = FragmentCountCheck()
        payload = _payload("<1/>p</>q\n[=[END]=]")
        source = _FakeSource(texts={0: "x</>y", 1: "p</>q"})
        assert check.run(payload, source) == []
