"""Entrées validées manuellement : la graphie ne doit pas les rendre invisibles.

Les clés `user` sont rangées sous leur forme normalisée parce que toutes les
lectures les cherchent ainsi — `collect_entry` dans un texte normalisé du même
geste, les deux collecteurs dans leur exclusion des entrées apprises, `learn`
dans son court-circuit. Une clé conservée dans sa graphie d'origine traverse le
glossaire sans jamais être trouvée : le terme n'est ni injecté dans les prompts
de traduction, ni protégé des propositions du LLM.

La graphie saisie, elle, survit dans le champ `terme` : c'est elle que les
prompts revoient, et l'utilisateur l'a écrite comme le livre.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ebook_translator.glossary import Glossary
from template.phase.glossary_models import LLMTermeGlossary


def _terme(terme: str, traduction: str) -> LLMTermeGlossary:
    """Entrée de glossaire telle que produite par `LLMGlossaryModel.build()`.

    Args:
        terme: Terme source, dans la casse où le LLM l'a émis.
        traduction: Proposition de traduction.

    Returns:
        L'entrée correspondante.
    """
    return {
        "terme": terme,
        "type": "terme_technique",
        "sexe": "f",
        "proposition_traduction": traduction,
    }


@pytest.fixture
def glossaire() -> Glossary:
    """Glossaire portant une entrée user saisie en casse mixte."""
    return Glossary().add_user_translation(
        "Matrix", "Matrice", sexe="f", terme_type="terme_technique"
    )


BLOC = "neo entered the matrix and stared at the screen"


class TestCollecte:
    """Ce que l'entrée user devient face au texte."""

    def test_entree_user_retrouvee_dans_le_texte(self, glossaire: Glossary) -> None:
        """La clé cherchée est normalisée ; la graphie saisie est ce qui ressort."""
        termes = {e["terme"] for e in glossaire.collect_entry(BLOC)}

        assert "Matrix" in termes

    def test_traduction_validee_conservee(self, glossaire: Glossary) -> None:
        entree = next(
            e for e in glossaire.collect_entry(BLOC) if e["terme"] == "Matrix"
        )

        assert entree["traduction"] == "Matrice"
        assert entree["confidence"] == "high"


class TestAutorite:
    """L'entrée user prime sur ce que le LLM propose."""

    def test_proposition_llm_ignoree(self, glossaire: Glossary) -> None:
        """Le LLM émet le terme dans sa casse d'origine, pas dans celle de la clé."""
        glossaire.learn(_terme("Matrix", "la Matrice"))

        assert glossaire.get_term_count() == 0

    def test_terme_user_non_collecte_en_double(self, glossaire: Glossary) -> None:
        """Sans exclusion, le terme figurerait à la fois en `user` et en appris."""
        glossaire.learn(_terme("Matrix", "la Matrice"))

        termes = [e["terme"] for e in glossaire.collect_entry(BLOC)]

        assert termes.count("Matrix") == 1

    def test_terme_user_absent_des_conflits(self, glossaire: Glossary) -> None:
        glossaire.learn(_terme("Matrix", "la Matrice"))

        assert glossaire.collect_entry_with_conflicts(BLOC) == []


class TestPersistance:
    """Un cache écrit avant la normalisation porte des clés en casse mixte."""

    def test_cle_normalisee_a_l_import(self, tmp_path: Path) -> None:
        source = tmp_path / "glossary.json"
        source.write_text(
            json.dumps(
                {
                    "glossary": {},
                    "user": {
                        "Matrix": {
                            "terme": "matrix",
                            "traduction": "Matrice",
                            "type": "terme_technique",
                            "sexe": "f",
                            "confidence": "high",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        termes = {e["terme"] for e in Glossary(source).collect_entry(BLOC)}

        assert "matrix" in termes

    def test_aller_retour_disque(self, glossaire: Glossary, tmp_path: Path) -> None:
        chemin = tmp_path / "glossary.json"
        glossaire.save(chemin)

        recharge = Glossary(chemin)

        assert recharge.get_statistics()["user_terms"] == 1
        assert {e["terme"] for e in recharge.collect_entry(BLOC)} == {"Matrix"}
