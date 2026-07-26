"""Check : couverture des indices attendus dans une `LineIndexedLLMResponse`.

Émet `ValidationFailure[LinesMissingDiagnostic]` listant les indices que le
LLM n'a pas traduits. Aucun `expected_count` ni autre métadonnée : la liste
des indices manquants suffit au retry ciblé en mode `merge`.
"""

from __future__ import annotations

from typing import ClassVar, override

from template.phase.translation_models import LineIndexed

from ...validation.diagnostics import ErreursType, LinesMissingDiagnostic
from ...validation.failure import ValidationFailure
from ...validation.retry_strategy import RetryStrategy
from ..content_check import ChunkSource, ContentCheck


class LineCountCheck(ContentCheck[LineIndexed, LinesMissingDiagnostic]):
    """Toutes les lignes attendues sont présentes dans le payload."""

    error_type: ClassVar[ErreursType] = ErreursType.LINES_MISSING
    retry_strategy: ClassVar[RetryStrategy] = RetryStrategy.PROGRESSIVE_REASONING
    max_attempts: ClassVar[int] = 2

    @override
    def run(
        self, data: LineIndexed, source: ChunkSource
    ) -> list[ValidationFailure[LinesMissingDiagnostic]]:
        expected = set(source.line_indices)
        missing = sorted(expected - data.keys())
        if not missing:
            return []
        return [
            ValidationFailure[LinesMissingDiagnostic](
                error_type=ErreursType.LINES_MISSING,
                msg=f"{len(missing)} lignes manquantes sur {len(expected)}",
                ctx={"missing_indices": missing},
                relevant_indices=frozenset(missing),
                check_source=type(self),
            )
        ]
