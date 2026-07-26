"""Check : préservation du nombre de paires de guillemets par ligne.

Émet **une `ValidationFailure[PunctuationDiagnostic]` par ligne en échec**.
Mode `replace` côté registre, `RetryPunctuationParams` traite une ligne à
la fois — chaque failure pilote un retry indépendant.

Couvre les guillemets anglais doubles (“ ” U+201C/U+201D) et français
(« »). Les guillemets simples ne sont pas comptés (cas trop ambigu :
apostrophes, élision).
"""

from __future__ import annotations

from typing import ClassVar, override

from template.phase.translation_models import LineIndexed

from ...validation.diagnostics import ErreursType, PunctuationDiagnostic
from ...validation.failure import ValidationFailure
from ...validation.retry_strategy import RetryStrategy
from ..content_check import ChunkSource, ContentCheck

_QUOTE_CHARS = ("“", "”", "«", "»")


def _count_quote_pairs(text: str) -> int:
    total = sum(text.count(c) for c in _QUOTE_CHARS)
    return total // 2


class PunctuationCheck(ContentCheck[LineIndexed, PunctuationDiagnostic]):
    """Le nombre de paires de guillemets par ligne est préservé."""

    error_type: ClassVar[ErreursType] = ErreursType.PUNCTUATION_MISMATCH
    retry_strategy: ClassVar[RetryStrategy] = RetryStrategy.NORMAL_ONLY
    max_attempts: ClassVar[int] = 2

    @override
    def run(
        self, data: LineIndexed, source: ChunkSource
    ) -> list[ValidationFailure[PunctuationDiagnostic]]:
        failures: list[ValidationFailure[PunctuationDiagnostic]] = []
        for index in source.line_indices:
            if index not in data:
                continue
            expected = _count_quote_pairs(source.text_at(index))
            actual = _count_quote_pairs(data[index])
            if expected == actual:
                continue
            failures.append(
                ValidationFailure[PunctuationDiagnostic](
                    error_type=ErreursType.PUNCTUATION_MISMATCH,
                    msg=(
                        f"ligne {index}: {actual} paire(s) de guillemets, "
                        f"{expected} attendue(s)"
                    ),
                    ctx={
                        "line": index,
                        "expected_pairs": expected,
                        "actual_pairs": actual,
                    },
                    relevant_indices=frozenset({index}),
                    check_source=type(self),
                )
            )
        return failures
