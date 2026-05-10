"""Tests du nouveau `PunctuationCheck`."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ebook_translator.checks.content.punctuation_check import PunctuationCheck
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


class TestPunctuationCheck:
    def test_error_type_is_class_level(self):
        assert PunctuationCheck.error_type is ErreursType.PUNCTUATION_MISMATCH

    def test_french_quotes_match(self):
        check = PunctuationCheck()
        payload = _payload("<0/>« Bonjour » dit-il\n[=[END]=]")
        source = _FakeSource(texts={0: "“Hello” he said"})
        assert check.run(payload, source) == []

    def test_missing_pair_returns_failure(self):
        check = PunctuationCheck()
        payload = _payload("<0/>Bonjour dit-il\n[=[END]=]")
        source = _FakeSource(texts={0: "“Hello” he said"})
        failures = check.run(payload, source)
        assert len(failures) == 1
        f = failures[0]
        assert f.error_type is ErreursType.PUNCTUATION_MISMATCH
        assert f.ctx["line"] == 0
        assert f.ctx["expected_pairs"] == 1
        assert f.ctx["actual_pairs"] == 0

    def test_one_failure_per_offending_line(self):
        check = PunctuationCheck()
        payload = _payload(
            "<0/>« A » dit-il\n<1/>« B sans fin\n<2/>« C » fin\n<3/>D plein\n[=[END]=]"
        )
        source = _FakeSource(
            texts={
                0: "“A” he said",
                1: "“B” he said",
                2: "“C” end",
                3: "“D” full",
            }
        )
        failures = check.run(payload, source)
        # Lignes 1 et 3 fautives (0 et 2 OK).
        assert len(failures) == 2
        offending = sorted(f.ctx["line"] for f in failures)
        assert offending == [1, 3]

    def test_no_quotes_anywhere(self):
        check = PunctuationCheck()
        payload = _payload("<0/>Bonjour\n<1/>Monde\n[=[END]=]")
        source = _FakeSource(texts={0: "Hello", 1: "World"})
        assert check.run(payload, source) == []
