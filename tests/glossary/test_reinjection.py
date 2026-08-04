"""Politique de réinjection du glossaire dans le prompt de sa propre phase.

Chaque appel LLM est isolé : `glossary_existing_block.jinja` est le seul canal
qui relie deux chunks. Ce qu'il montre — et ce qu'il tait — décide si un terme
peut accumuler du poids ou reste condamné à réapparaître sous une forme voisine.
"""

from __future__ import annotations

import pytest

from ebook_translator.glossary import (
    DEFAULT_MIN_REINJECTION_WEIGHT,
    Glossary,
    converged_weight,
)
from ebook_translator.llm.template_renderers import PhaseTemplate, TemplateRenderer
from template.phase.glossary_models import LLMTermeGlossary


def _terme(terme: str, traduction: str) -> LLMTermeGlossary:
    """Entrée de glossaire telle que produite par `LLMGlossaryModel.build()`.

    Args:
        terme: Terme source.
        traduction: Proposition de traduction.

    Returns:
        L'entrée correspondante.
    """
    return {
        "terme": terme,
        "type": "personnage",
        "sexe": "m",
        "proposition_traduction": traduction,
    }


@pytest.fixture
def glossaire() -> Glossary:
    """Glossaire portant un terme lourd, un terme moyen et un terme léger."""
    g = Glossary()
    for _ in range(converged_weight()):
        g.learn(_terme("john", "john"))
    for _ in range(DEFAULT_MIN_REINJECTION_WEIGHT):
        g.learn(_terme("nursery", "la nursery"))
    g.learn(_terme("nursery", "la chambre d'enfants"))
    g.learn(_terme("yellow wallpaper", "le papier peint jaune"))
    return g


BLOC = "john entered the nursery and stared at the yellow wallpaper"


class TestCollecte:
    """Ce que `collect_entry_with_conflicts` remonte."""

    def test_terme_leger_reste_collecte(self, glossaire: Glossary) -> None:
        """Le filtrer le rendait invisible : le LLM le réémettait sous une variante."""
        termes = {e["terme"] for e in glossaire.collect_entry_with_conflicts(BLOC)}

        assert "yellow wallpaper" in termes

    def test_terme_absent_du_bloc_non_collecte(self, glossaire: Glossary) -> None:
        termes = {
            e["terme"] for e in glossaire.collect_entry_with_conflicts("rien à voir")
        }

        assert termes == set()

    def test_poids_rapporte_tel_quel(self, glossaire: Glossary) -> None:
        poids = {
            e["terme"]: e["weight"]
            for e in glossaire.collect_entry_with_conflicts(BLOC)
        }

        assert poids["yellow wallpaper"] == 1
        assert poids["nursery"] == DEFAULT_MIN_REINJECTION_WEIGHT + 1


class TestRendu:
    """Ce que le prompt montre effectivement au modèle."""

    @pytest.fixture
    def prompt(self, glossaire: Glossary) -> str:
        """Prompt système de la phase glossaire, glossaire existant inclus."""
        systeme, _ = TemplateRenderer().render_prompt(
            PhaseTemplate.Glossary,
            block_text=BLOC,
            target_language="français",
            genre="fiction",
            existing_glossary=glossaire.collect_entry_with_conflicts(BLOC),
            min_reinjection_weight=DEFAULT_MIN_REINJECTION_WEIGHT,
        )
        return systeme

    def test_terme_stable_exclu_de_la_sortie(self, prompt: str) -> None:
        section = prompt[prompt.index("**Termes validés**") :]
        assert "john" in section[: section.index("**Termes à arbitrer**")]

    def test_terme_arbitrable_montre_ses_propositions(self, prompt: str) -> None:
        section = prompt[prompt.index("**Termes à arbitrer**") :]
        arbitrage = section[: section.index("**Termes déjà extraits**")]

        assert "nursery" in arbitrage
        assert "la chambre d'enfants" in arbitrage

    def test_terme_leger_montre_sans_sa_traduction(self, prompt: str) -> None:
        """Une proposition isolée ancrerait le modèle sur une supposition."""
        section = prompt[prompt.index("**Termes déjà extraits**") :]

        assert "`yellow wallpaper`" in section
        assert "le papier peint jaune" not in section

    def test_conditions_d_admission_rappelees(self, prompt: str) -> None:
        """Sans ce rappel, la liste vaudrait invitation à tout réémettre."""
        section = prompt[prompt.index("**Termes déjà extraits**") :]

        assert "conditions d'admission" in section
