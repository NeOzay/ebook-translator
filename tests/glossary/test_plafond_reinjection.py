"""Borne du bloc « Glossaire existant » quand le glossaire est prérempli.

Ce bloc n'est pas mis en cache — son contenu dépend du chunk courant — et pèse
déjà environ 40 % du prompt système sur un livre long appris en cours de route.
Rien n'en limitait la taille : un glossaire prérempli par import de plusieurs
tomes ou par seed pouvait le faire enfler sans borne.

Le plafond arbitre par groupe avant de le faire par fréquence. Un terme
émergent est rare par construction ; le couper parce qu'il est rare, c'est
garantir qu'il restera invisible, donc réémis en variante, donc jamais convergé.
"""

from __future__ import annotations

import pytest

from ebook_translator.glossary import (
    DEFAULT_MAX_REINJECTED_TERMS,
    DEFAULT_MIN_REINJECTION_WEIGHT,
    Glossary,
    converged_weight,
    reinjection_group,
)
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


def _peupler(glossaire: Glossary, prefixe: str, nombre: int, poids: int) -> list[str]:
    """Ajoute des termes distincts partageant le même poids.

    Args:
        glossaire: Glossaire à peupler.
        prefixe: Préfixe des termes générés.
        nombre: Nombre de termes à créer.
        poids: Nombre d'émissions par terme.

    Returns:
        Les termes créés.
    """
    termes = [f"{prefixe}{i:03d}" for i in range(nombre)]
    for terme in termes:
        for _ in range(poids):
            glossaire.learn(_terme(terme, f"{terme} traduit"))
    return termes


class TestGroupe:
    """`reinjection_group` reproduit le découpage du template."""

    @pytest.mark.parametrize(
        ("poids", "attendu"),
        [
            (1, "emergent"),
            (DEFAULT_MIN_REINJECTION_WEIGHT, "arbitrer"),
            (converged_weight(), "valide"),
        ],
    )
    def test_poids_unanime(self, poids: int, attendu: str) -> None:
        glossaire = Glossary()
        _ = _peupler(glossaire, "t", 1, poids)

        entree = glossaire.get_translations_until_confidence("t000", 0.7)

        assert entree is not None
        assert reinjection_group(entree) == attendu


class TestPlafond:
    """Ce que la troncature garde et ce qu'elle laisse tomber."""

    @pytest.fixture
    def glossaire(self) -> Glossary:
        """Glossaire dépassant le plafond, réparti sur les trois groupes."""
        g = Glossary()
        _ = _peupler(g, "valide", 40, converged_weight())
        _ = _peupler(g, "arbitre", 40, DEFAULT_MIN_REINJECTION_WEIGHT)
        _ = _peupler(g, "emerge", 40, 1)
        return g

    @pytest.fixture
    def bloc(self, glossaire: Glossary) -> str:
        """Bloc employant tous les termes du glossaire, une fois chacun."""
        return " ".join(sorted(glossaire._glossary))  # pyright: ignore[reportPrivateUsage]

    def test_plafond_respecte(self, glossaire: Glossary, bloc: str) -> None:
        assert len(glossaire.collect_entry_with_conflicts(bloc, max_terms=50)) == 50

    def test_arbitrables_conserves_en_premier(
        self, glossaire: Glossary, bloc: str
    ) -> None:
        retenus = glossaire.collect_entry_with_conflicts(bloc, max_terms=40)

        assert {reinjection_group(e) for e in retenus} == {"arbitrer"}

    def test_emergents_avant_valides(self, glossaire: Glossary, bloc: str) -> None:
        """Un validé omis reste stable ; un émergent omis revient en variante."""
        groupes = {
            reinjection_group(e)
            for e in glossaire.collect_entry_with_conflicts(bloc, max_terms=80)
        }

        assert groupes == {"arbitrer", "emergent"}

    def test_frequence_departage_dans_un_groupe(self, glossaire: Glossary) -> None:
        bloc = "arbitre000 " * 5 + " ".join(f"arbitre{i:03d}" for i in range(1, 40))

        retenus = glossaire.collect_entry_with_conflicts(bloc, max_terms=1)

        assert [e["terme"] for e in retenus] == ["arbitre000"]


class TestSousLePlafond:
    """En deçà de la borne, rien ne change."""

    def test_ordre_de_decouverte_preserve(self) -> None:
        glossaire = Glossary()
        termes = _peupler(glossaire, "t", 5, 1)
        bloc = " ".join(reversed(termes))

        retenus = glossaire.collect_entry_with_conflicts(bloc)

        assert [e["terme"] for e in retenus] == termes

    def test_livre_long_reel_sous_le_plafond(self) -> None:
        """Mesuré sur un tome complet : 54 termes au plus par bloc."""
        assert DEFAULT_MAX_REINJECTED_TERMS > 54
