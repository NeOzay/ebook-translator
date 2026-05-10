"""Check : préservation du nombre de séparateurs `</>` par ligne.

Émet **une `ValidationFailure[FragmentDiagnostic]` par ligne en échec**.
Cohérent avec le mode `replace` du registre et `RetryFragmentsParams` qui
traite une ligne à la fois — chaque failure pilote un retry indépendant.
"""

from __future__ import annotations

from typing import ClassVar, override

from ...constants import FRAGMENT_SEPARATOR
from ...validation.diagnostics import ErreursType, FragmentDiagnostic
from ...validation.failure import ValidationFailure
from ...validation.retry_strategy import RetryStrategy
from ..content_check import ChunkSource, ContentCheck


class FragmentCountCheck(ContentCheck[dict[int, str], FragmentDiagnostic]):
    """Le nombre de `</>` par ligne traduite égale celui de la source."""

    error_type: ClassVar[ErreursType] = ErreursType.FRAGMENT_COUNT_MISMATCH
    retry_strategy: ClassVar[RetryStrategy] = RetryStrategy.PROGRESSIVE_REASONING
    max_attempts: ClassVar[int] = 2

    @override
    def run(
        self, data: dict[int, str], source: ChunkSource
    ) -> list[ValidationFailure[FragmentDiagnostic]]:
        failures: list[ValidationFailure[FragmentDiagnostic]] = []
        for index in source.line_indices:
            if index not in data:
                continue
            expected = source.text_at(index).count(FRAGMENT_SEPARATOR)
            actual = data[index].count(FRAGMENT_SEPARATOR)
            if expected == actual:
                continue
            failures.append(
                ValidationFailure[FragmentDiagnostic](
                    error_type=ErreursType.FRAGMENT_COUNT_MISMATCH,
                    msg=(
                        f"ligne {index}: {actual} séparateur(s) </>, "
                        f"{expected} attendu(s)"
                    ),
                    ctx={
                        "line": index,
                        "expected_pairs": expected,
                        "actual_pairs": actual,
                    },
                )
            )
        return failures
