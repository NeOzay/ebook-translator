"""Résolution du glossaire de départ par le `PipelineBuilder`.

Un run peut partir de rien, d'un glossaire hérité d'un tome précédent, d'un
seed déclaratif, ou des deux à la fois. La résolution a lieu au `build()` pour
que l'ordre des appels n'ait aucune incidence : dans une API fluide, un ordre
signifiant est un piège.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ebook_translator.glossary import Glossary
from ebook_translator.llm.clients.deepseek import Deepseek, DeepseekModels
from ebook_translator.pipeline.builder import (
    LLMBuilder,
    PhasesBuilder,
    PipelineBuilder,
)
from template.phase.glossary_models import LLMTermeGlossary

SEED = """
[[entree]]
terme = "nursery"
traduction = "la nursery"
type = "lieu"
sexe = "f"
niveau = "arbitrer"
"""


@pytest.fixture(autouse=True)
def _api_key(  # pyright: ignore[reportUnusedFunction]  # fixture autouse
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Évite la lecture du `.env` et le `sys.exit(1)` de `get_api_key`."""
    monkeypatch.setenv("API_KEY", "sk-test-not-a-real-key")


@pytest.fixture
def epub_path() -> Path:
    """EPUB court servant de source aux builders de test."""
    return Path("tests/Saint-Exupery-Le_Petit_Prince.epub")


@pytest.fixture
def seed(tmp_path: Path) -> Path:
    """Fichier de seed portant un terme unique."""
    chemin = tmp_path / "seed.toml"
    _ = chemin.write_text(SEED, encoding="utf-8")
    return chemin


@pytest.fixture
def builder(tmp_path: Path, epub_path: Path) -> PipelineBuilder:
    """Builder minimal valide, sans glossaire."""
    return (
        PipelineBuilder()
        .epub(epub_path)
        .output(tmp_path / "out.epub")
        .cache_dir(tmp_path / "cache")
        .language("français")
        .llm(LLMBuilder().default_client(Deepseek(DeepseekModels.FLASH)))
        .phases(PhasesBuilder().add_initial_translation())
    )


def _glossaire(builder: PipelineBuilder) -> Glossary | None:
    """Extrait le glossaire résolu des paramètres de run.

    Args:
        builder: Builder à construire.

    Returns:
        Le glossaire transmis à `run()`, ou `None` si le run part à froid.
    """
    _, run_kwargs = builder.build()
    glossaire = run_kwargs.get("glossary")
    assert glossaire is None or isinstance(glossaire, Glossary)
    return glossaire


class TestSansSeed:
    """Comportement inchangé quand aucun seed n'est déclaré."""

    def test_run_a_froid(self, builder: PipelineBuilder) -> None:
        assert _glossaire(builder) is None

    def test_glossaire_fourni_transmis_tel_quel(self, builder: PipelineBuilder) -> None:
        fourni = Glossary()
        assert _glossaire(builder.glossary(fourni)) is fourni


class TestAvecSeed:
    """Le seed peuple le glossaire de départ."""

    def test_seed_seul_construit_un_glossaire(
        self, builder: PipelineBuilder, seed: Path
    ) -> None:
        glossaire = _glossaire(builder.glossary_seed(seed))

        assert glossaire is not None
        assert glossaire.get_translation("nursery") is not None

    def test_seed_complete_le_glossaire_fourni(
        self, builder: PipelineBuilder, seed: Path
    ) -> None:
        """Cas visé : un tome précédent importé, puis un seed ciblé par-dessus."""
        fourni = Glossary()
        fourni.learn(
            LLMTermeGlossary(
                terme="john",
                type="personnage",
                sexe="m",
                proposition_traduction="John",
            )
        )

        glossaire = _glossaire(builder.glossary(fourni).glossary_seed(seed))

        assert glossaire is fourni
        assert {"john", "nursery"} <= set(fourni._glossary)  # pyright: ignore[reportPrivateUsage]

    def test_ordre_des_appels_indifferent(
        self, builder: PipelineBuilder, seed: Path
    ) -> None:
        fourni = Glossary()

        glossaire = _glossaire(builder.glossary_seed(seed).glossary(fourni))

        assert glossaire is fourni
        assert fourni.get_translation("nursery") is not None


class TestErreurs:
    """Un seed introuvable ou mal formé échoue au `build()`, pas en cours de run."""

    def test_fichier_absent(self, builder: PipelineBuilder, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            _ = builder.glossary_seed(tmp_path / "absent.toml").build()

    def test_fichier_mal_forme(self, builder: PipelineBuilder, tmp_path: Path) -> None:
        chemin = tmp_path / "seed.toml"
        _ = chemin.write_text('[[entree]]\nterme = "x"\n', encoding="utf-8")

        with pytest.raises(ValueError, match="`type`"):
            _ = builder.glossary_seed(chemin).build()
