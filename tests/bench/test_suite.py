"""Tests du modèle de configuration du banc d'essais (`bench/suite.py`)."""

import sys
from pathlib import Path

import pytest

from ebook_translator.bench.suite import (
    SEED_ID,
    BenchSuite,
    CorpusOptions,
    RunEnv,
    Seed,
    Variant,
    load_suite,
)
from ebook_translator.pipeline.base import PhaseName
from ebook_translator.pipeline.builder import PipelineBuilder


def build_stub(env: RunEnv) -> PipelineBuilder:
    """Fabrique inerte : le contenu du builder n'importe pas pour ces tests."""
    return PipelineBuilder().epub(env.epub).output(env.output).cache_dir(env.cache_dir)


@pytest.fixture
def epub(tmp_path: Path) -> Path:
    """EPUB source factice, dont seule l'existence compte."""
    path = tmp_path / "livre.epub"
    path.write_bytes(b"PK\x03\x04")
    return path


def make_variant(variant_id: str) -> Variant:
    return Variant(id=variant_id, params={"temperature": 0.5}, build=build_stub)


class TestVariant:
    @pytest.mark.parametrize("variant_id", ["v1", "flash-t05", "modele_a", "2"])
    def test_identifiants_valides(self, variant_id: str):
        assert make_variant(variant_id).id == variant_id

    @pytest.mark.parametrize("variant_id", ["V1", "avec espace", "-tiret", "accentué"])
    def test_identifiants_invalides(self, variant_id: str):
        with pytest.raises(ValueError, match="Variant id invalide"):
            make_variant(variant_id)

    def test_identifiant_seed_reserve(self):
        with pytest.raises(ValueError, match="réservé"):
            make_variant(SEED_ID)


class TestSeed:
    def test_phases_vides_refusees(self):
        with pytest.raises(ValueError, match="ne peut pas être vide"):
            Seed(build=build_stub, phases=())

    def test_phases_en_double_refusees(self):
        with pytest.raises(ValueError, match="doublons"):
            Seed(
                build=build_stub,
                phases=(PhaseName.GLOSSARY, PhaseName.GLOSSARY),
            )


class TestBenchSuite:
    def test_suite_minimale(self, epub: Path):
        suite = BenchSuite(epub=epub, variants=[make_variant("a"), make_variant("b")])

        assert suite.variant("b").id == "b"
        assert suite.shared_phases == ()
        assert suite.corpus == CorpusOptions()

    def test_une_seule_variante_refusee(self, epub: Path):
        with pytest.raises(ValueError, match="au moins 2 variantes"):
            BenchSuite(epub=epub, variants=[make_variant("a")])

    def test_identifiants_en_double_refuses(self, epub: Path):
        with pytest.raises(ValueError, match="en double"):
            BenchSuite(epub=epub, variants=[make_variant("a"), make_variant("a")])

    def test_epub_manquant_refuse(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            BenchSuite(
                epub=tmp_path / "absent.epub",
                variants=[make_variant("a"), make_variant("b")],
            )

    def test_variante_inconnue(self, epub: Path):
        suite = BenchSuite(epub=epub, variants=[make_variant("a"), make_variant("b")])

        with pytest.raises(KeyError, match="Variante inconnue"):
            suite.variant("z")

    def test_shared_phases_vient_du_seed(self, epub: Path):
        suite = BenchSuite(
            epub=epub,
            variants=[make_variant("a"), make_variant("b")],
            seed=Seed(build=build_stub, phases=(PhaseName.LITERARY_ANALYSIS,)),
        )

        assert suite.shared_phases == (PhaseName.LITERARY_ANALYSIS,)

    def test_factory_resout_seed_et_variantes(self, epub: Path):
        seed = Seed(build=build_stub, phases=(PhaseName.GLOSSARY,))
        variante = make_variant("a")
        suite = BenchSuite(epub=epub, variants=[variante, make_variant("b")], seed=seed)

        assert suite.factory(SEED_ID) is seed.build
        assert suite.factory("a") is variante.build

    def test_factory_seed_sans_seed_declare(self, epub: Path):
        suite = BenchSuite(epub=epub, variants=[make_variant("a"), make_variant("b")])

        with pytest.raises(KeyError, match="run d'amorçage"):
            suite.factory(SEED_ID)


class TestLoadSuite:
    def _write_config(self, tmp_path: Path, epub: Path, corps: str) -> Path:
        config = tmp_path / "config_bench.py"
        config.write_text(corps.format(epub=epub.as_posix()), encoding="utf-8")
        return config

    def test_charge_une_suite_valide(self, tmp_path: Path, epub: Path):
        config = self._write_config(
            tmp_path,
            epub,
            """
from pathlib import Path

from ebook_translator.bench.suite import BenchSuite, Variant
from ebook_translator.pipeline.builder import PipelineBuilder


def build(env):
    return PipelineBuilder()


suite = BenchSuite(
    epub=Path("{epub}"),
    variants=[
        Variant("a", {{"temperature": 0.5}}, build),
        Variant("b", {{"temperature": 1.0}}, build),
    ],
)
""",
        )

        suite = load_suite(config)

        assert [v.id for v in suite.variants] == ["a", "b"]
        assert suite.variant("b").params == {"temperature": 1.0}

    def test_script_absent(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_suite(tmp_path / "absent.py")

    def test_script_sans_variable_suite(self, tmp_path: Path, epub: Path):
        config = self._write_config(tmp_path, epub, "autre_chose = 1\n")

        with pytest.raises(AttributeError, match="n'expose pas de variable"):
            load_suite(config)

    def test_suite_du_mauvais_type(self, tmp_path: Path, epub: Path):
        config = self._write_config(tmp_path, epub, "suite = 42\n")

        with pytest.raises(TypeError, match="doit être une BenchSuite"):
            load_suite(config)

    def test_module_retire_si_le_script_leve(self, tmp_path: Path, epub: Path):
        config = self._write_config(tmp_path, epub, "raise RuntimeError('boum')\n")

        with pytest.raises(RuntimeError, match="boum"):
            load_suite(config)

        assert "ebook_translator_bench_config" not in sys.modules
