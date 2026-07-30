"""Tests de configuration : Phase 1 / Phase 2 déclarent bien leur contrat.

Vérifie que les deux phases exposent `payload_type` et `content_checks` au
niveau classe — les deux attributs que `PhaseExecutor` et
`UnifiedValidationWorker` lisent pour piloter schéma et corrections.

Aucun pipeline complet n'est invoqué ; on instancie la phase et on inspecte
ses attributs. Le comportement de validation lui-même est couvert côté
worker (`tests/validation/test_unified_worker.py`).
"""

from __future__ import annotations

import pytest

from ebook_translator.pipeline.phases.initial_translation import InitialTranslationPhase
from ebook_translator.pipeline.phases.refinement import RefinementPhase
from ebook_translator.validation.diagnostics import ErreursType
from template.phase.translation_models import LineIndexedLLMResponse


@pytest.fixture
def initial_phase() -> InitialTranslationPhase:
    return InitialTranslationPhase(max_tokens=1500)


@pytest.fixture
def refinement_phase() -> RefinementPhase:
    return RefinementPhase(max_tokens=300)


class TestInitialPhaseConfiguration:
    def test_payload_type(self, initial_phase: InitialTranslationPhase) -> None:
        assert initial_phase.payload_type is LineIndexedLLMResponse

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
        assert refinement_phase.payload_type is LineIndexedLLMResponse

    def test_content_checks_count(self, refinement_phase: RefinementPhase) -> None:
        assert len(refinement_phase.content_checks) == 4
