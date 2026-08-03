"""Tests de la sérialisation des résultats (`bench/results.py`)."""

from pathlib import Path

import pytest

from ebook_translator.bench.results import PhaseResult, VariantResult
from ebook_translator.llm.usage import PhaseUsage
from ebook_translator.pipeline.base import PhaseName
from ebook_translator.pipeline.context import PhaseStats


def make_phase(name: str = "initial", calls: int = 3) -> PhaseResult:
    return PhaseResult(
        name=name,
        chunks_total=10,
        chunks_processed=10,
        chunks_from_cache=2,
        chunks_translated=8,
        chunks_validated=9,
        chunks_rejected=1,
        duration_seconds=12.3456,
        usage=PhaseUsage(calls, 1000, 400, 100, 50),
    )


class TestPhaseResult:
    def test_depuis_phase_stats(self):
        stats = PhaseStats(phase_name=PhaseName.INITIAL)
        stats.chunks_total = 4
        stats.chunks_from_cache = 4
        stats.usage = PhaseUsage(0, 0, 0, 0, 0)

        result = PhaseResult.from_stats(stats)

        assert result.name == str(PhaseName.INITIAL)
        assert result.chunks_total == 4
        assert result.usage.llm_calls == 0

    def test_aller_retour_json(self):
        phase = make_phase()

        assert PhaseResult.from_dict(phase.to_dict()) == PhaseResult(
            **{**vars(phase), "duration_seconds": 12.346}
        )

    def test_champs_manquants_tolerés(self):
        phase = PhaseResult.from_dict({"name": "glossary"})

        assert phase.chunks_total == 0
        assert phase.usage == PhaseUsage()


class TestVariantResult:
    def test_usage_cumule_les_phases(self):
        result = VariantResult(
            variant_id="v1",
            phases=(make_phase("initial", 3), make_phase("refinement", 2)),
        )

        assert result.usage.llm_calls == 5
        assert result.usage.prompt_tokens == 2000

    def test_recherche_de_phase(self):
        result = VariantResult(variant_id="v1", phases=(make_phase("initial"),))

        assert result.phase("initial") is not None
        assert result.phase("glossary") is None

    def test_aller_retour_fichier(self, tmp_path: Path):
        result = VariantResult(
            variant_id="v1",
            phases=(make_phase(),),
            duration_seconds=42.0,
            seeded_phases=("literary analysis",),
        )
        chemin = tmp_path / "sous-dossier" / "result.json"

        result.write(chemin)

        relu = VariantResult.read(chemin)
        assert relu.variant_id == "v1"
        assert relu.status == "ok"
        assert relu.seeded_phases == ("literary analysis",)
        assert relu.usage.llm_calls == 3

    def test_statut_erreur_conserve_le_message(self, tmp_path: Path):
        chemin = tmp_path / "result.json"
        VariantResult(variant_id="v1", status="error", error="boum").write(chemin)

        relu = VariantResult.read(chemin)

        assert relu.status == "error"
        assert relu.error == "boum"

    def test_lecture_fichier_absent(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            _ = VariantResult.read(tmp_path / "absent.json")
