"""Tests du sous-processus d'exécution d'une variante (`bench/worker.py`)."""

from collections.abc import Callable
from pathlib import Path

import pytest

from ebook_translator.bench.results import RESULT_FILENAME, VariantResult
from ebook_translator.bench.suite import RunEnv
from ebook_translator.bench.worker import _check_env_honored, execute, main


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
