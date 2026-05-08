"""Tests d'intégration : Phase 1 / Phase 2 sur la nouvelle API `validate`.

Vérifie que les deux phases exposent correctement `payload_type` et
`content_checks` au niveau classe, et que `phase.validate(raw, source)`
fonctionne bout en bout.

Aucun pipeline complet n'est invoqué ; on instancie la phase et on appelle
sa méthode `validate` directement.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pytest

from ebook_translator.pipeline.phases.initial_translation import InitialTranslationPhase
from ebook_translator.pipeline.phases.refinement import RefinementPhase
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


@pytest.fixture
def initial_phase() -> InitialTranslationPhase:
    return InitialTranslationPhase(max_tokens=1500)


@pytest.fixture
def refinement_phase() -> RefinementPhase:
    return RefinementPhase(max_tokens=300)


class TestInitialPhaseConfiguration:
    def test_payload_type(self, initial_phase: InitialTranslationPhase) -> None:
        assert initial_phase.payload_type is LineIndexedTranslation

    def test_content_checks_count(self, initial_phase: InitialTranslationPhase) -> None:
        assert len(initial_phase.content_checks) == 4

    def test_content_check_error_types(
        self, initial_phase: InitialTranslationPhase
    ) -> None:
        types = {c.error_type for c in initial_phase.content_checks}
        assert types == {
            ErreursType.LINES_MISSING,
            ErreursType.FRAGMENT_COUNT_MISMATCH,
            ErreursType.PUNCTUATION_MISMATCH,
            ErreursType.SENTENCE_INVALID,
        }


class TestRefinementPhaseConfiguration:
    def test_payload_type(self, refinement_phase: RefinementPhase) -> None:
        assert refinement_phase.payload_type is LineIndexedTranslation

    def test_content_checks_count(self, refinement_phase: RefinementPhase) -> None:
        assert len(refinement_phase.content_checks) == 4


class TestInitialPhaseValidate:
    def test_valid_payload_returns_model(
        self, initial_phase: InitialTranslationPhase
    ) -> None:
        source = _FakeSource(
            texts={
                0: "Hello </> world.",
                1: "“Hi.”",
            }
        )
        raw = "<0/>Bonjour </> monde.\n<1/>« Salut. »\n[=[END]=]"
        result = initial_phase.validate(raw, source)
        assert isinstance(result, LineIndexedTranslation)
        assert result.lines[0] == "Bonjour </> monde."
        assert result.lines[1] == "« Salut. »"

    def test_schema_failure_short_circuits_checks(
        self, initial_phase: InitialTranslationPhase
    ) -> None:
        source = _FakeSource(texts={0: "Hello.", 1: "World."})
        raw = "<0/>Bonjour.\n<1/>Monde."  # marqueur absent
        result = initial_phase.validate(raw, source)
        assert isinstance(result, list)
        assert any(f.error_type is ErreursType.MISSING_END_MARKER for f in result)

    def test_content_failures_aggregate_across_checks(
        self, initial_phase: InitialTranslationPhase
    ) -> None:
        # Schéma OK ; mais ligne 1 manquante (LineCount), ligne 0 fragment KO.
        source = _FakeSource(texts={0: "Hello </> world.", 1: "Hi."})
        raw = "<0/>Bonjour monde.\n[=[END]=]"  # 0 séparateur au lieu de 1
        result = initial_phase.validate(raw, source)
        assert isinstance(result, list)
        error_types = {f.error_type for f in result}
        assert ErreursType.LINES_MISSING in error_types
        assert ErreursType.FRAGMENT_COUNT_MISMATCH in error_types


class TestRefinementPhaseValidate:
    def test_valid_payload_returns_model(
        self, refinement_phase: RefinementPhase
    ) -> None:
        source = _FakeSource(texts={0: "Hello.", 1: "World."})
        raw = "<0/>Bonjour.\n<1/>Monde.\n[=[END]=]"
        result = refinement_phase.validate(raw, source)
        assert isinstance(result, LineIndexedTranslation)
