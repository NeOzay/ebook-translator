"""Tests de la nouvelle API `validate` de `PhaseBase`.

Vérifie les quatre cas du plan :
    1. Schéma OK + contenu OK   → retourne `M`
    2. Schéma KO                → retourne failures Pydantic typées
    3. Schéma OK + contenu KO   → retourne failures content
    4. Schéma KO                → checks contenu NE TOURNENT PAS

Test direct sur la fonction libre `validate_payload`. Le wrapper
`PhaseBase.validate` n'ajoute aucune logique : la fonction libre suffit
à couvrir la sémantique sans construire un `PhaseBase` complet.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar

from ebook_translator.checks.content_check import ChunkSource
from ebook_translator.pipeline.base import validate_payload
from ebook_translator.validation.diagnostics import (
    ErreursType,
    LinesMissingDiagnostic,
)
from ebook_translator.validation.failure import ValidationFailure
from ebook_translator.validation.retry_strategy import RetryStrategy
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


class _AlwaysFailLineCount:
    """Check qui produit toujours une `LinesMissingDiagnostic`. Sert de
    sentinelle pour vérifier qu'un check ne tourne PAS quand le schéma KO."""

    error_type: ClassVar[ErreursType] = ErreursType.LINES_MISSING
    retry_strategy: ClassVar[RetryStrategy] = RetryStrategy.NORMAL_ONLY
    max_attempts: ClassVar[int] = 1

    def __init__(self) -> None:
        self.calls = 0

    def run(
        self,
        payload: LineIndexedTranslation,
        source: ChunkSource,
    ) -> list[ValidationFailure[LinesMissingDiagnostic]]:
        self.calls += 1
        return [
            ValidationFailure[LinesMissingDiagnostic](
                error_type=ErreursType.LINES_MISSING,
                msg="forcé",
                ctx={"missing_indices": [0]},
            )
        ]


class TestValidatePayload:
    def test_schema_ok_no_checks_returns_payload(self):
        result = validate_payload(
            payload_type=LineIndexedTranslation,
            content_checks=(),
            raw="<0/>a\n<1/>b\n[=[END]=]",
            source=_FakeSource(indices=(0, 1)),
        )
        assert isinstance(result, LineIndexedTranslation)
        assert result.lines == {0: "a", 1: "b"}

    def test_schema_ok_content_ok_returns_payload(self):
        from ebook_translator.checks.content.line_count_check import LineCountCheck

        result = validate_payload(
            payload_type=LineIndexedTranslation,
            content_checks=(LineCountCheck(),),
            raw="<0/>a\n<1/>b\n[=[END]=]",
            source=_FakeSource(indices=(0, 1)),
        )
        assert isinstance(result, LineIndexedTranslation)

    def test_schema_ko_missing_end_marker_returns_pydantic_failures(self):
        result = validate_payload(
            payload_type=LineIndexedTranslation,
            content_checks=(),
            raw="<0/>a\n<1/>b",
            source=_FakeSource(indices=(0, 1)),
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].error_type is ErreursType.MISSING_END_MARKER

    def test_schema_ko_short_circuits_content_checks(self):
        sentinel = _AlwaysFailLineCount()
        result = validate_payload(
            payload_type=LineIndexedTranslation,
            content_checks=(sentinel,),
            raw="<0/>a",  # marqueur absent
            source=_FakeSource(indices=(0, 1)),
        )
        assert isinstance(result, list)
        assert result[0].error_type is ErreursType.MISSING_END_MARKER
        # Critère du plan : check contenu NE TOURNE PAS si schéma KO.
        assert sentinel.calls == 0

    def test_schema_ok_content_ko_returns_content_failures(self):
        from ebook_translator.checks.content.line_count_check import LineCountCheck

        result = validate_payload(
            payload_type=LineIndexedTranslation,
            content_checks=(LineCountCheck(),),
            raw="<0/>a\n[=[END]=]",
            source=_FakeSource(indices=(0, 1, 2)),
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].error_type is ErreursType.LINES_MISSING
        assert result[0].ctx["missing_indices"] == [1, 2]

    def test_already_validated_payload_passthrough(self):
        already = LineIndexedTranslation.model_validate("<0/>a\n[=[END]=]")
        result = validate_payload(
            payload_type=LineIndexedTranslation,
            content_checks=(),
            raw=already,
            source=_FakeSource(indices=(0,)),
        )
        # Identité : même instance, pas de re-validation.
        assert result is already

    def test_already_validated_payload_runs_content_checks(self):
        from ebook_translator.checks.content.line_count_check import LineCountCheck

        already = LineIndexedTranslation.model_validate("<0/>a\n[=[END]=]")
        result = validate_payload(
            payload_type=LineIndexedTranslation,
            content_checks=(LineCountCheck(),),
            raw=already,
            source=_FakeSource(indices=(0, 1)),
        )
        assert isinstance(result, list)
        assert result[0].error_type is ErreursType.LINES_MISSING

    def test_multiple_content_failures_all_collected(self):
        from ebook_translator.checks.content.line_count_check import LineCountCheck

        sentinel = _AlwaysFailLineCount()
        result = validate_payload(
            payload_type=LineIndexedTranslation,
            content_checks=(LineCountCheck(), sentinel),
            raw="<0/>a\n[=[END]=]",
            source=_FakeSource(indices=(0, 1)),
        )
        assert isinstance(result, list)
        assert len(result) == 2
        assert sentinel.calls == 1
