"""Tests du nouveau `SentenceCheck`."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ebook_translator.checks.content.sentence_check import SentenceCheck
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


class TestSentenceCheck:
    def test_error_type_is_class_level(self):
        assert SentenceCheck.error_type is ErreursType.SENTENCE_INVALID

    def test_matching_counts_returns_empty(self):
        check = SentenceCheck()
        payload = _payload("<0/>Bonjour. Monde !\n<1/>Salut ?\n[=[END]=]")
        source = _FakeSource(texts={0: "Hello. World!", 1: "Hi?"})
        assert check.run(payload, source) == []

    def test_mismatch_returns_one_aggregated_failure(self):
        check = SentenceCheck()
        payload = _payload("<0/>Bonjour\n<1/>Salut. Et toi.\n<2/>Ok.\n[=[END]=]")
        source = _FakeSource(texts={0: "Hello. World.", 1: "Hi.", 2: "Ok."})
        failures = check.run(payload, source)
        assert len(failures) == 1
        assert failures[0].error_type is ErreursType.SENTENCE_INVALID
        assert failures[0].ctx["invalid_indices"] == [0, 1]

    def test_indices_are_sorted(self):
        check = SentenceCheck()
        payload = _payload("<5/>Bonjour\n<2/>Salut. Et toi.\n[=[END]=]")
        source = _FakeSource(texts={5: "Hello. End.", 2: "Hi."})
        failures = check.run(payload, source)
        assert len(failures) == 1
        assert failures[0].ctx["invalid_indices"] == [2, 5]

    def test_missing_lines_skipped(self):
        check = SentenceCheck()
        payload = _payload("<0/>Bonjour.\n[=[END]=]")
        source = _FakeSource(texts={0: "Hello.", 1: "World."})
        assert check.run(payload, source) == []
