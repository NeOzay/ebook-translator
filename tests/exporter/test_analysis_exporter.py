"""Tests de l'export Markdown d'une fiche `AnalyseChapter` (Phase 0)."""

from pathlib import Path
from typing import get_args

import pytest
from pydantic import BaseModel

from ebook_translator.exporter.analysis_exporter import (
    NARRATIVE_LABELS,
    NOYAU_LABELS,
    SIGNAL_LABELS,
    AnalysisExporter,
    _checked_labels,  # pyright: ignore[reportPrivateUsage]
    _checked_signal_labels,  # pyright: ignore[reportPrivateUsage]
    export_to_markdown,
)
from template.phase.analyze_chapter_layered_models import (
    AnalyseChapter,
    CoucheNarrative,
    NoyauStable,
    SignalCloture,
)


@pytest.fixture
def analyse() -> AnalyseChapter:
    """Fiche d'analyse complète, avec un arc résolu et un arc actif."""
    return AnalyseChapter.model_validate(
        {
            "chapitre": "Chapitre 1",
            "noyau_stable": {
                "genre_affine": "conte philosophique",
                "registre": "  soutenu   et   limpide ",
                "style_auctorial": "phrases courtes",
                "tonalite_generale": "mélancolique",
                "pistes_traduction": ["garder le tutoiement", "éviter l'argot"],
            },
            "couche_narrative": {
                "resume_narratif": "Le narrateur rencontre le petit prince.",
                "arcs_en_cours": [
                    {"arc": "la panne dans le désert", "signal_cloture": "aucun"},
                    {
                        "arc": "le dessin du mouton",
                        "signal_cloture": "resolution_explicite",
                    },
                ],
                "tensions": ["l'eau qui manque"],
                "themes_emergents": ["l'enfance"],
                "references_culturelles_rencontrees": [],
            },
        }
    )


class TestExportToMarkdown:
    """Rendu Markdown de la fiche stratifiée."""

    def test_titre_et_sections_principales(self, analyse: AnalyseChapter) -> None:
        markdown = export_to_markdown(analyse)

        assert markdown.startswith("# Chapitre 1")
        assert "## Noyau stable" in markdown
        assert "## Couche narrative" in markdown

    def test_normalise_les_espaces(self, analyse: AnalyseChapter) -> None:
        markdown = export_to_markdown(analyse)

        assert "soutenu et limpide" in markdown

    def test_pistes_rendues_en_puces(self, analyse: AnalyseChapter) -> None:
        markdown = export_to_markdown(analyse)

        assert "- garder le tutoiement" in markdown
        assert "- éviter l'argot" in markdown

    def test_signal_de_cloture_annote_les_arcs(self, analyse: AnalyseChapter) -> None:
        markdown = export_to_markdown(analyse)

        # `aucun` = arc actif, `resolution_explicite` = arc résolu.
        assert "- la panne dans le désert (actif)" in markdown
        assert "- le dessin du mouton (résolu)" in markdown

    def test_liste_vide_rend_un_placeholder(self, analyse: AnalyseChapter) -> None:
        markdown = export_to_markdown(analyse)

        assert "> Aucune entrée fournie." in markdown

    def test_sommaire_present_au_dessus_du_seuil(self, analyse: AnalyseChapter) -> None:
        # 10 sous-sections au total (5 noyau + 5 narrative) ≥ seuil.
        assert "## Sommaire" in export_to_markdown(analyse, toc_threshold=5)

    def test_sommaire_desactivable(self, analyse: AnalyseChapter) -> None:
        assert "## Sommaire" not in export_to_markdown(analyse, toc_threshold=False)


class TestSaveAnalysisMarkdown:
    """Écriture sur disque."""

    def test_ecrit_le_fichier(self, analyse: AnalyseChapter, tmp_path: Path) -> None:
        output = tmp_path / "Chapitre_1.md"

        AnalysisExporter.save_analysis_markdown(analyse, output)

        assert output.read_text(encoding="utf-8").startswith("# Chapitre 1")


class TestLabelSchemaGuard:
    """Garde-fous d'import : les libellés doivent suivre le schéma.

    Sans eux, un champ ajouté à `NoyauStable` ou `CoucheNarrative`
    disparaîtrait silencieusement de l'export Markdown.
    """

    def test_noyau_labels_couvrent_le_modele(self) -> None:
        assert set(NOYAU_LABELS) == set(NoyauStable.model_fields)

    def test_narrative_labels_couvrent_le_modele(self) -> None:
        assert set(NARRATIVE_LABELS) == set(CoucheNarrative.model_fields)

    def test_signal_labels_couvrent_le_literal(self) -> None:
        assert set(SIGNAL_LABELS) == set(get_args(SignalCloture))

    def test_champ_sans_libelle_leve(self) -> None:
        class _Modele(BaseModel):
            connu: str
            oublie: str

        with pytest.raises(ValueError, match=r"champs sans libellé \['oublie'\]"):
            _checked_labels(_Modele, {"connu": "Connu"})

    def test_libelle_sans_champ_leve(self) -> None:
        class _Modele(BaseModel):
            connu: str

        with pytest.raises(ValueError, match=r"libellés sans champ \['disparu'\]"):
            _checked_labels(_Modele, {"connu": "Connu", "disparu": "Disparu"})

    def test_signal_incomplet_leve(self) -> None:
        with pytest.raises(ValueError, match="SignalCloture"):
            _checked_signal_labels({"aucun": "actif"})
