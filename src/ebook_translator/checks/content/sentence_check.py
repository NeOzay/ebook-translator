"""Check : conservation du nombre de phrases par ligne.

Émet une seule `ValidationFailure[SentenceDiagnostic]` agrégeant **toutes**
les lignes invalides. Mode `merge` côté registre : le retry corrige
plusieurs lignes en un appel.

Le compteur de phrases utilise une heuristique simple (split sur `.!?`)
identique au check legacy. Limitation connue : sur-comptage en présence
d'abréviations avec point.
"""

from __future__ import annotations

import re
from typing import ClassVar, override

from template.phase.translation_models import LineIndexed

from ...validation.diagnostics import ErreursType, SentenceDiagnostic
from ...validation.failure import ValidationFailure
from ...validation.retry_strategy import RetryStrategy
from ..content_check import ChunkSource, ContentCheck

_SENTENCE_END = re.compile(r"[.!?]+")


def _count_sentences(text: str) -> int:
    parts = [p for p in _SENTENCE_END.split(text.strip()) if p.strip()]
    return len(parts)


class SentenceCheck(ContentCheck[LineIndexed, SentenceDiagnostic]):
    """Le nombre de phrases par ligne est préservé entre source et traduction."""

    error_type: ClassVar[ErreursType] = ErreursType.SENTENCE_INVALID
    retry_strategy: ClassVar[RetryStrategy] = RetryStrategy.PROGRESSIVE_REASONING
    max_attempts: ClassVar[int] = 2

    @override
    def run(
        self, data: LineIndexed, source: ChunkSource
    ) -> list[ValidationFailure[SentenceDiagnostic]]:
        invalid: list[int] = []
        for index in source.line_indices:
            if index not in data:
                continue
            if _count_sentences(source.text_at(index)) != _count_sentences(data[index]):
                invalid.append(index)
        if not invalid:
            return []
        return [
            ValidationFailure[SentenceDiagnostic](
                error_type=ErreursType.SENTENCE_INVALID,
                msg=f"{len(invalid)} ligne(s) avec un nombre de phrases incorrect",
                ctx={"invalid_indices": sorted(invalid)},
                relevant_indices=frozenset(invalid),
                check_source=type(self),
            )
        ]
