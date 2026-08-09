"""Tests de l'orchestration d'un run (`bench/runner.py`)."""

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from ebook_translator.bench import runner
from ebook_translator.bench.results import RESULT_FILENAME, VariantResult
from ebook_translator.bench.runner import (
    CONFIG_COPY_NAME,
    WORK_DIRNAME,
    SeedFailedError,
    new_run_id,
    run_suite,
)
from ebook_translator.bench.suite import SEED_ID
from ebook_translator.logger import get_session_log_path

SEED_EXTRA = "seed=Seed(build=build, phases=(PhaseName.LITERARY_ANALYSIS,)),"


@pytest.fixture
def executions(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Remplace le lancement de sous-processus par un succès instantané.

    Les tests d'orchestration portent sur l'enchaînement seed → variantes, pas
    sur l'exécution d'un pipeline réel (qui demanderait un appel API).

    Returns:
        La liste, alimentée au fil des appels, des variantes lancées.
    """
    lancees: list[str] = []

    def fake_execute(config: Path, variant_id: str, work_root: Path) -> VariantResult:
        lancees.append(variant_id)
        result = VariantResult(variant_id=variant_id, status="ok")
        result.write(work_root / variant_id / RESULT_FILENAME)
        return result

    monkeypatch.setattr(runner, "_execute_variant", fake_execute)
    return lancees


def seed_le_cache(root: Path, phase: str = "literary analysis") -> None:
    """Peuple le cache d'amorçage comme l'aurait fait un vrai run."""
    store = root / WORK_DIRNAME / SEED_ID / "cache" / phase
    store.mkdir(parents=True, exist_ok=True)
    (store / "bloc.json").write_text(json.dumps({"0": "fiche"}), encoding="utf-8")


class TestNewRunId:
    def test_format_horodate(self):
        assert new_run_id(datetime(2026, 8, 2, 14, 30, 5)) == "20260802_143005"


class TestRunSuite:
    def test_execute_toutes_les_variantes(
        self, tmp_path: Path, write_config: Callable[..., Path], executions: list[str]
    ):
        config = write_config()

        run = run_suite(config, runs_dir=tmp_path / "runs", run_id="essai")

        assert executions == ["a", "b"]
        assert [v.variant_id for v in run.variants] == ["a", "b"]
        assert run.seed is None
        assert run.root == tmp_path / "runs" / "essai"

    def test_conserve_une_copie_de_la_config(
        self, tmp_path: Path, write_config: Callable[..., Path], executions: list[str]
    ):
        config = write_config()

        run = run_suite(config, runs_dir=tmp_path / "runs", run_id="essai")

        assert (run.root / CONFIG_COPY_NAME).read_text(
            encoding="utf-8"
        ) == config.read_text(encoding="utf-8")

    def test_redirige_les_logs_du_harness_dans_le_run(
        self, tmp_path: Path, write_config: Callable[..., Path], executions: list[str]
    ):
        config = write_config()

        run = run_suite(config, runs_dir=tmp_path / "runs", run_id="essai")

        # La collecte et le rapport s'exécutent ensuite dans ce processus : la
        # redirection doit les couvrir aussi.
        assert get_session_log_path("collect.log").parent == run.root / "logs"

    def test_only_restreint_la_selection(
        self, tmp_path: Path, write_config: Callable[..., Path], executions: list[str]
    ):
        config = write_config()

        run = run_suite(config, runs_dir=tmp_path / "runs", run_id="essai", only=["b"])

        assert executions == ["b"]
        assert [v.variant_id for v in run.variants] == ["b"]

    def test_only_inconnu(
        self, tmp_path: Path, write_config: Callable[..., Path], executions: list[str]
    ):
        config = write_config()

        with pytest.raises(KeyError, match="Variante inconnue"):
            _ = run_suite(
                config, runs_dir=tmp_path / "runs", run_id="essai", only=["zzz"]
            )

    def test_amorcage_partage_la_phase(
        self,
        tmp_path: Path,
        write_config: Callable[..., Path],
        monkeypatch: pytest.MonkeyPatch,
    ):
        config = write_config(extra=SEED_EXTRA)
        root = tmp_path / "runs" / "essai"

        def fake_execute(
            config_path: Path, variant_id: str, work_root: Path
        ) -> VariantResult:
            if variant_id == SEED_ID:
                seed_le_cache(root)
            result = VariantResult(variant_id=variant_id, status="ok")
            result.write(work_root / variant_id / RESULT_FILENAME)
            return result

        monkeypatch.setattr(runner, "_execute_variant", fake_execute)

        run = run_suite(config, runs_dir=tmp_path / "runs", run_id="essai")

        assert run.seed is not None and run.seed.status == "ok"
        for variant in run.variants:
            assert variant.seeded_phases == ("literary analysis",)
            fiche = (
                run.work_root / variant.variant_id / "cache" / "literary analysis"
            ) / "bloc.json"
            assert json.loads(fiche.read_text(encoding="utf-8")) == {"0": "fiche"}

    def test_echec_de_l_amorcage_arrete_tout(
        self,
        tmp_path: Path,
        write_config: Callable[..., Path],
        monkeypatch: pytest.MonkeyPatch,
    ):
        config = write_config(extra=SEED_EXTRA)

        def fake_execute(
            config_path: Path, variant_id: str, work_root: Path
        ) -> VariantResult:
            return VariantResult(variant_id=variant_id, status="error", error="boum")

        monkeypatch.setattr(runner, "_execute_variant", fake_execute)

        with pytest.raises(SeedFailedError, match="boum"):
            _ = run_suite(config, runs_dir=tmp_path / "runs", run_id="essai")

    def test_echec_d_une_variante_n_interrompt_pas(
        self,
        tmp_path: Path,
        write_config: Callable[..., Path],
        monkeypatch: pytest.MonkeyPatch,
    ):
        config = write_config()

        def fake_execute(
            config_path: Path, variant_id: str, work_root: Path
        ) -> VariantResult:
            statut = "error" if variant_id == "a" else "ok"
            result = VariantResult(
                variant_id=variant_id,
                status="error" if statut == "error" else "ok",
                error="boum" if statut == "error" else None,
            )
            result.write(work_root / variant_id / RESULT_FILENAME)
            return result

        monkeypatch.setattr(runner, "_execute_variant", fake_execute)

        run = run_suite(config, runs_dir=tmp_path / "runs", run_id="essai")

        assert [v.variant_id for v in run.failed] == ["a"]
        assert [v.variant_id for v in run.succeeded] == ["b"]


class TestExecuteVariant:
    def test_resultat_manquant_devient_une_erreur(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        class FauxProcessus:
            returncode = 137

        monkeypatch.setattr(
            runner.subprocess,
            "run",
            lambda *a, **k: FauxProcessus(),  # type: ignore[misc]
        )

        result = runner._execute_variant(tmp_path / "config.py", "a", tmp_path / "work")

        assert result.status == "error"
        assert result.error is not None
        assert "137" in result.error
