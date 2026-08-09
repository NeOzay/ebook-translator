"""Tests du sous-processus d'exécution d'une variante (`bench/worker.py`)."""

from collections.abc import Callable
from pathlib import Path

import pytest

from ebook_translator.bench.results import RESULT_FILENAME, VariantResult
from ebook_translator.bench.suite import RunEnv
from ebook_translator.bench.worker import _check_env_honored, execute, main
from ebook_translator.bench.workspace import variant_logs_dir
from ebook_translator.logger import get_session_log_path

from .conftest import BUILD_QUI_TRAITE


def make_env(tmp_path: Path) -> RunEnv:
    return RunEnv(
        variant_id="a",
        epub=tmp_path / "livre.epub",
        output=tmp_path / "sortie.epub",
        cache_dir=tmp_path / "cache",
        workspace=tmp_path,
    )


class TestCheckEnvHonored:
    def test_chemins_conformes(self, tmp_path: Path):
        env = make_env(tmp_path)

        _check_env_honored(env.epub, env.cache_dir, env)

    def test_cache_ignore_par_la_fabrique(self, tmp_path: Path):
        env = make_env(tmp_path)

        with pytest.raises(ValueError, match="cache_dir"):
            _check_env_honored(env.epub, tmp_path / "ailleurs", env)

    def test_epub_ignore_par_la_fabrique(self, tmp_path: Path):
        env = make_env(tmp_path)

        with pytest.raises(ValueError, match="epub"):
            _check_env_honored(tmp_path / "autre.epub", env.cache_dir, env)


class TestExecute:
    def test_echec_de_fabrique_capture(
        self, tmp_path: Path, write_config: Callable[..., Path]
    ):
        config = write_config()

        result = execute(config, "a", tmp_path / "work")

        assert result.status == "error"
        assert result.error is not None
        assert "fabrique cassée" in result.error
        assert result.variant_id == "a"

    def test_workspace_cree_meme_en_echec(
        self, tmp_path: Path, write_config: Callable[..., Path]
    ):
        config = write_config()

        _ = execute(config, "a", tmp_path / "work")

        assert (tmp_path / "work" / "a" / "cache").is_dir()

    def test_variante_inconnue(self, tmp_path: Path, write_config: Callable[..., Path]):
        config = write_config()

        result = execute(config, "inexistante", tmp_path / "work")

        assert result.status == "error"
        assert result.error is not None
        assert "Variante inconnue" in result.error


class TestStatutCalcule:
    """Le statut d'une variante dérive du travail accompli, pas de l'absence d'erreur.

    Un run étranglé par le débit rendait la main sans exception avec
    `chunks_processed: 0`, et le banc le déclarait « ok » : son corpus vide
    entrait alors dans l'arbitrage (run de banc vide déclaré réussi, 2026-08-04).
    """

    def test_travail_complet_est_ok(
        self, tmp_path: Path, write_config: Callable[..., Path]
    ):
        config = write_config(BUILD_QUI_TRAITE.format(total=4, processed=4))

        result = execute(config, "a", tmp_path / "work")

        assert result.status == "ok"
        assert result.error is None

    def test_rien_de_traite_est_une_erreur(
        self, tmp_path: Path, write_config: Callable[..., Path]
    ):
        config = write_config(BUILD_QUI_TRAITE.format(total=4, processed=0))

        result = execute(config, "a", tmp_path / "work")

        assert result.status == "error"
        assert result.error is not None
        assert "0/4" in result.error

    def test_travail_partiel_est_signale(
        self, tmp_path: Path, write_config: Callable[..., Path]
    ):
        config = write_config(BUILD_QUI_TRAITE.format(total=4, processed=1))

        result = execute(config, "a", tmp_path / "work")

        assert result.status == "partial"
        assert result.error is not None
        assert "1/4" in result.error

    def test_le_statut_survit_au_tour_par_json(
        self, tmp_path: Path, write_config: Callable[..., Path]
    ):
        config = write_config(BUILD_QUI_TRAITE.format(total=4, processed=1))
        work_root = tmp_path / "work"

        code = main(
            ["--config", str(config), "--variant", "a", "--work-root", str(work_root)]
        )

        # `from_dict` repliait tout ce qui n'était pas « ok » sur « error ».
        assert VariantResult.read(work_root / "a" / RESULT_FILENAME).status == "partial"
        assert code == 1


class TestMain:
    def test_ecrit_le_resultat_et_sort_en_erreur(
        self, tmp_path: Path, write_config: Callable[..., Path]
    ):
        config = write_config()
        work_root = tmp_path / "work"

        code = main(
            ["--config", str(config), "--variant", "a", "--work-root", str(work_root)]
        )

        assert code == 1
        result = VariantResult.read(work_root / "a" / RESULT_FILENAME)
        assert result.status == "error"

    def test_redirige_les_logs_dans_le_workspace(
        self, tmp_path: Path, write_config: Callable[..., Path]
    ):
        config = write_config()
        work_root = tmp_path / "work"

        _ = main(
            ["--config", str(config), "--variant", "a", "--work-root", str(work_root)]
        )

        # La fabrique lève : la trace de l'échec doit rester avec la variante,
        # pas partir dans le `logs/run_<horodatage>/` du répertoire courant.
        logs = variant_logs_dir(work_root, "a")
        assert get_session_log_path("llm_0001.log").parent == logs
        assert list(logs.glob("*.log")), "aucun log écrit dans le workspace"
