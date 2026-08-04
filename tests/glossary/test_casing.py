"""Casse des propositions de traduction.

Le décompte porte sur la forme minuscule — `Jean` et `jean` sont la même
proposition et doivent cumuler leur poids, sans quoi la convergence recule. La
graphie est suivie séparément, pour que les phases 1 et 2 reçoivent `Jean` et
non `jean` : un glossaire dominé par des anthroponymes ne peut pas être restitué
en bas de casse.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ebook_translator.glossary import Glossary
from template.phase.glossary_models import LLMTermeGlossary


def _terme(terme: str, traduction: str) -> LLMTermeGlossary:
    """Entrée telle que produite par `LLMGlossaryModel.build()`.

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


class TestApprentissage:
    """Ce que `learn` retient."""

    def test_graphie_restituee(self) -> None:
        g = Glossary()
        g.learn(_terme("john", "Jean"))

        entry = g.get_translation("john")
        assert entry is not None
        assert entry["traduction"] == "Jean"

    def test_casse_differente_ne_scinde_pas_le_poids(self) -> None:
        """Deux graphies d'une même proposition restent une seule proposition."""
        g = Glossary()
        g.learn(_terme("john", "Jean"))
        g.learn(_terme("john", "jean"))

        entry = g.get_translation("john")
        assert entry is not None
        assert entry["weight"] == 2
        conflits = g.get_conflicts()
        assert len(conflits["john"]["traductions"]) == 1

    def test_graphie_dominante_l_emporte(self) -> None:
        g = Glossary()
        g.learn(_terme("john", "jean"))
        g.learn(_terme("john", "Jean"))
        g.learn(_terme("john", "Jean"))

        entry = g.get_translation("john")
        assert entry is not None
        assert entry["traduction"] == "Jean"

    def test_terme_source_reste_minuscule(self) -> None:
        """La clé source est une clé d'agrégation, cherchée dans un texte minusculé."""
        g = Glossary()
        g.learn(_terme("John", "Jean"))

        assert g.get_translation("john") is not None

    def test_propositions_concurrentes_gardent_leur_graphie(self) -> None:
        g = Glossary()
        g.learn(_terme("john", "Jean"))
        g.learn(_terme("john", "Johnny"))

        detail = g.get_translations_until_confidence("john", confidence=1)
        assert detail is not None
        assert {t for t, _ in detail["traductions"]} == {"Jean", "Johnny"}

    def test_traduction_utilisateur_conserve_sa_casse(self) -> None:
        g = Glossary()
        _ = g.add_user_translation("matrix", "Matrice", sexe="f", terme_type="objet")

        entrees = g.collect_entry("they entered the matrix at dawn")
        assert [e["traduction"] for e in entrees] == ["Matrice"]


class TestPersistance:
    """Aller-retour sur disque."""

    def test_graphie_survit_a_l_aller_retour(self, tmp_path: Path) -> None:
        chemin = tmp_path / "glossary.json"
        g = Glossary()
        g.learn(_terme("john", "Jean"))
        g.save(chemin)

        recharge = Glossary(chemin)

        entry = recharge.get_translation("john")
        assert entry is not None
        assert entry["traduction"] == "Jean"

    def test_cache_sans_graphies_reste_lisible(self, tmp_path: Path) -> None:
        """Un cache écrit avant ce suivi ne doit pas faire échouer la lecture."""
        chemin = tmp_path / "glossary.json"
        _ = chemin.write_text(
            json.dumps(
                {
                    "glossary": {
                        "john": {
                            "translations": {"jean": 3},
                            "term_types": {"personnage": 3},
                            "sexes": {"m": 3},
                        }
                    },
                    "user": {},
                }
            ),
            encoding="utf-8",
        )

        entry = Glossary(chemin).get_translation("john")

        assert entry is not None
        assert entry["traduction"] == "jean"

    def test_graphies_fusionnees_a_l_import(self, tmp_path: Path) -> None:
        """Le decay pondère les propositions, pas la façon de les écrire."""
        precedent = tmp_path / "vol1.json"
        source = Glossary()
        for _ in range(10):
            source.learn(_terme("john", "Jean"))
        source.save(precedent)

        courant = Glossary()
        courant.learn(_terme("john", "jean"))
        courant.import_from_volume(precedent, decay=0.1)

        entry = courant.get_translation("john")
        assert entry is not None
        assert entry["traduction"] == "Jean"


@pytest.mark.parametrize("proposition", ["Weir Mitchell", "la véranda", "l'Ancien"])
def test_graphie_rendue_a_l_identique(proposition: str) -> None:
    """Aucune normalisation : ce que le LLM a écrit est ce qui ressort."""
    g = Glossary()
    g.learn(_terme("x", proposition))

    entry = g.get_translation("x")
    assert entry is not None
    assert entry["traduction"] == proposition
