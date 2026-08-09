"""Tests de l'isolation des variantes (`bench/workspace.py`)."""

import json
from pathlib import Path

import pytest

from ebook_translator.bench.workspace import (
    CACHE_DIRNAME,
    prepare_workspace,
    seed_shared_phases,
    variant_logs_dir,
)
from ebook_translator.pipeline.base import PhaseName


@pytest.fixture
def epub(tmp_path: Path) -> Path:
    """EPUB source factice, partagé par les variantes."""
    source = tmp_path / "source" / "Mon Livre.epub"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"PK\x03\x04")
    return source


class TestVariantLogsDir:
    def test_dans_le_workspace_de_la_variante(self, tmp_path: Path):
        chemin = variant_logs_dir(tmp_path / "work", "v1")

        assert chemin == tmp_path / "work" / "v1" / "logs"

    def test_pas_cree_par_la_derivation(self, tmp_path: Path):
        # Le sous-processus se redirige avant que le workspace n'existe : la
        # création revient au premier log (`LazyFileHandler`).
        assert not variant_logs_dir(tmp_path / "work", "v1").exists()

    def test_coherent_avec_run_env(self, tmp_path: Path, epub: Path):
        env = prepare_workspace(tmp_path / "work", "v1", epub)

        assert env.logs_dir == variant_logs_dir(tmp_path / "work", "v1")
        assert env.logs_dir.parent == env.workspace


class TestPrepareWorkspace:
    def test_cree_workspace_lien_et_cache(self, tmp_path: Path, epub: Path):
        env = prepare_workspace(tmp_path / "work", "v1", epub)

        assert env.variant_id == "v1"
        assert env.workspace == tmp_path / "work" / "v1"
        assert env.cache_dir == env.workspace / CACHE_DIRNAME
        assert env.cache_dir.is_dir()
        assert env.epub.read_bytes() == b"PK\x03\x04"
        assert env.epub.parent == env.workspace

    def test_sortie_distincte_de_la_source(self, tmp_path: Path, epub: Path):
        env = prepare_workspace(tmp_path / "work", "v1", epub)

        assert env.output != env.epub
        assert env.output.parent == env.workspace
        assert env.output.suffix == ".epub"

    def test_variantes_isolees(self, tmp_path: Path, epub: Path):
        un = prepare_workspace(tmp_path / "work", "v1", epub)
        deux = prepare_workspace(tmp_path / "work", "v2", epub)

        assert un.workspace != deux.workspace
        assert un.cache_dir != deux.cache_dir
        # Le glossaire s'exporte à côté de l'EPUB : la séparation des parents
        # est ce qui empêche les variantes de s'écraser.
        assert un.epub.parent != deux.epub.parent

    def test_idempotent(self, tmp_path: Path, epub: Path):
        premier = prepare_workspace(tmp_path / "work", "v1", epub)
        (premier.cache_dir / "trace.txt").write_text("x", encoding="utf-8")

        second = prepare_workspace(tmp_path / "work", "v1", epub)

        assert second == premier
        assert (second.cache_dir / "trace.txt").exists()

    def test_epub_absent(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            prepare_workspace(tmp_path / "work", "v1", tmp_path / "absent.epub")


class TestSeedSharedPhases:
    def _seed_cache(self, tmp_path: Path, phase: PhaseName) -> Path:
        cache = tmp_path / "seed" / CACHE_DIRNAME
        store = cache / str(phase)
        store.mkdir(parents=True)
        (store / "chapitre.json").write_text(
            json.dumps({"0": "texte"}), encoding="utf-8"
        )
        return cache

    def test_copie_le_store_partage(self, tmp_path: Path, epub: Path):
        phase = PhaseName.LITERARY_ANALYSIS
        seed_cache = self._seed_cache(tmp_path, phase)
        env = prepare_workspace(tmp_path / "work", "v1", epub)

        copiees = seed_shared_phases(seed_cache, env, [phase])

        assert copiees == [phase]
        copie = env.cache_dir / str(phase) / "chapitre.json"
        assert json.loads(copie.read_text(encoding="utf-8")) == {"0": "texte"}

    def test_copie_et_non_lien(self, tmp_path: Path, epub: Path):
        phase = PhaseName.GLOSSARY
        seed_cache = self._seed_cache(tmp_path, phase)
        env = prepare_workspace(tmp_path / "work", "v1", epub)
        _ = seed_shared_phases(seed_cache, env, [phase])

        # Une variante qui réécrit son cache ne doit pas toucher la référence.
        (env.cache_dir / str(phase) / "chapitre.json").write_text(
            json.dumps({"0": "modifié"}), encoding="utf-8"
        )

        origine = seed_cache / str(phase) / "chapitre.json"
        assert json.loads(origine.read_text(encoding="utf-8")) == {"0": "texte"}

    def test_ecrase_une_copie_precedente(self, tmp_path: Path, epub: Path):
        phase = PhaseName.GLOSSARY
        seed_cache = self._seed_cache(tmp_path, phase)
        env = prepare_workspace(tmp_path / "work", "v1", epub)
        parasite = env.cache_dir / str(phase) / "parasite.json"
        parasite.parent.mkdir(parents=True)
        parasite.write_text("{}", encoding="utf-8")

        _ = seed_shared_phases(seed_cache, env, [phase])

        assert not parasite.exists()
        assert (env.cache_dir / str(phase) / "chapitre.json").exists()

    def test_phase_absente_du_seed(self, tmp_path: Path, epub: Path):
        seed_cache = self._seed_cache(tmp_path, PhaseName.GLOSSARY)
        env = prepare_workspace(tmp_path / "work", "v1", epub)

        with pytest.raises(FileNotFoundError, match="absente du cache d'amorçage"):
            _ = seed_shared_phases(seed_cache, env, [PhaseName.LITERARY_ANALYSIS])

    def test_sans_phase_partagee(self, tmp_path: Path, epub: Path):
        seed_cache = self._seed_cache(tmp_path, PhaseName.GLOSSARY)
        env = prepare_workspace(tmp_path / "work", "v1", epub)

        assert seed_shared_phases(seed_cache, env, []) == []
