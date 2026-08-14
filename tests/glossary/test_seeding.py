"""Préremplissage déclaratif : ce que le seed fait voir au modèle.

Un seed n'a d'intérêt que s'il place le terme dans le groupe visé du prompt de
la phase glossaire. La vérification porte donc sur le prompt rendu, pas sur les
compteurs internes : c'est le texte reçu par le modèle qui décide de son
comportement, et les poids ne sont qu'un moyen d'y arriver.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ebook_translator.glossary import DEFAULT_MIN_REINJECTION_WEIGHT, Glossary
from ebook_translator.glossary_seed import apply_seed, load_seed, poids_pour_niveau
from ebook_translator.llm.template_renderers import PhaseTemplate, TemplateRenderer
from template.phase.glossary_models import LLMTermeGlossary

SEED = """
[[entree]]
terme = "john"
traduction = "John"
type = "personnage"
sexe = "m"
niveau = "valide"

[[entree]]
terme = "nursery"
type = "lieu"
sexe = "f"
propositions = [["la nursery", 3], ["la chambre d'enfants", 2]]

[[entree]]
terme = "yellow wallpaper"
traduction = "le papier peint jaune"
type = "objet"
sexe = "m"
niveau = "emergent"

[[entree]]
terme = "Matrix"
traduction = "Matrice"
type = "terme_technique"
sexe = "f"
user = true
"""

BLOC = (
    "john entered the nursery, stared at the yellow wallpaper "
    "and thought about the matrix"
)


@pytest.fixture
def seed(tmp_path: Path) -> Path:
    """Fichier de seed couvrant les trois niveaux et une entrée user."""
    chemin = tmp_path / "seed.toml"
    _ = chemin.write_text(SEED, encoding="utf-8")
    return chemin


@pytest.fixture
def glossaire(seed: Path) -> Glossary:
    """Glossaire issu du seed."""
    return load_seed(seed)


@pytest.fixture
def prompt(glossaire: Glossary) -> str:
    """Prompt système de la phase glossaire, glossaire seedé inclus."""
    systeme, _ = TemplateRenderer().render_prompt(
        PhaseTemplate.Glossary,
        block_text=BLOC,
        target_language="français",
        genre="fiction",
        existing_glossary=glossaire.collect_entry_with_conflicts(BLOC),
        min_reinjection_weight=DEFAULT_MIN_REINJECTION_WEIGHT,
    )
    return systeme


def _section(prompt: str, debut: str, fin: str | None) -> str:
    """Extrait une section du prompt entre deux en-têtes.

    Args:
        prompt: Prompt système rendu.
        debut: En-tête ouvrant la section.
        fin: En-tête de la section suivante, ou `None` jusqu'à la fin.

    Returns:
        Le texte de la section.
    """
    reste = prompt[prompt.index(debut) :]
    return reste if fin is None else reste[: reste.index(fin)]


class TestNiveaux:
    """Chaque niveau atterrit dans le groupe qu'il vise."""

    def test_valide_montre_sans_etre_reemis(self, prompt: str) -> None:
        section = _section(prompt, "**Termes validés**", "**Termes à arbitrer**")

        assert "john" in section

    def test_propositions_montrees_avec_leurs_poids(self, prompt: str) -> None:
        section = _section(prompt, "**Termes à arbitrer**", "**Termes déjà extraits**")

        assert "nursery" in section
        assert "`la nursery` (3)" in section
        assert "`la chambre d'enfants` (2)" in section

    def test_emergent_montre_sans_sa_traduction(self, prompt: str) -> None:
        """Une proposition isolée ancrerait le modèle sur une supposition."""
        section = _section(prompt, "**Termes déjà extraits**", None)

        assert "`yellow wallpaper`" in section
        assert "le papier peint jaune" not in section

    def test_entree_user_hors_du_bloc_existant(self, prompt: str) -> None:
        """Une entrée validée n'a rien à arbitrer : elle passe par les phases 1/2."""
        assert "Matrice" not in prompt


class TestEntreeUser:
    """L'entrée `user` suit le canal des phases de traduction."""

    def test_injectee_dans_les_prompts_de_traduction(self, glossaire: Glossary) -> None:
        entree = next(
            e for e in glossaire.collect_entry(BLOC) if e["terme"] == "Matrix"
        )

        assert entree["traduction"] == "Matrice"

    def test_casse_du_fichier_sans_effet(self, glossaire: Glossary) -> None:
        """Le seed écrit `Matrix` ; les lectures cherchent `matrix`."""
        glossaire.learn(
            LLMTermeGlossary(
                terme="Matrix",
                type="terme_technique",
                sexe="f",
                proposition_traduction="la matrice",
            )
        )

        assert "matrix" not in glossaire._glossary  # pyright: ignore[reportPrivateUsage]


class TestPoids:
    """Les poids dérivent des seuils du glossaire, ils ne sont pas codés en dur."""

    def test_emergent_reste_sous_le_seuil_de_reinjection(self) -> None:
        assert poids_pour_niveau("emergent") < DEFAULT_MIN_REINJECTION_WEIGHT

    def test_arbitrer_atteint_le_seuil_sans_converger(self) -> None:
        assert poids_pour_niveau("arbitrer") >= DEFAULT_MIN_REINJECTION_WEIGHT
        assert poids_pour_niveau("arbitrer") < poids_pour_niveau("valide")

    def test_valide_atteint_la_confiance_haute(self, glossaire: Glossary) -> None:
        entree = glossaire.get_translation("john")

        assert entree is not None
        assert entree["confidence"] == "high"


class TestCumul:
    """Un seed complète un glossaire existant plutôt que de le remplacer."""

    def test_applique_sur_un_glossaire_peuple(self, seed: Path) -> None:
        glossaire = Glossary()
        glossaire.learn(
            LLMTermeGlossary(
                terme="john",
                type="personnage",
                sexe="m",
                proposition_traduction="Jean",
            )
        )

        _ = apply_seed(glossaire, seed)
        entree = glossaire.get_translations_until_confidence("john", 1.0)

        assert entree is not None
        assert dict(entree["traductions"])["Jean"] == 1


class TestErreurs:
    """Un seed mal formé échoue à la lecture, pas au milieu d'un run."""

    @pytest.mark.parametrize(
        ("contenu", "attendu"),
        [
            ('[[entree]]\ntype = "lieu"\nsexe = "f"\nniveau = "emergent"', "`terme`"),
            (
                '[[entree]]\nterme = "x"\ntype = "vaisseau"\nsexe = "f"\nniveau = "emergent"',
                "type `vaisseau` inconnu",
            ),
            (
                '[[entree]]\nterme = "x"\ntype = "lieu"\nsexe = "n"\nniveau = "emergent"',
                "sexe `n` inconnu",
            ),
            (
                '[[entree]]\nterme = "x"\ntraduction = "y"\ntype = "lieu"\nsexe = "f"\nniveau = "stable"',
                "niveau `stable` inconnu",
            ),
            (
                '[[entree]]\nterme = "x"\ntraduction = "y"\ntype = "lieu"\nsexe = "f"\n'
                'niveau = "emergent"\npropositions = [["z", 1]]',
                "exclusifs",
            ),
            (
                '[[entree]]\nterme = "x"\ntraduction = "y"\ntype = "lieu"\nsexe = "f"\n'
                'user = true\nniveau = "valide"',
                "ni `niveau` ni `propositions`",
            ),
            (
                '[[entree]]\nterme = "x"\ntype = "lieu"\nsexe = "f"\npropositions = [["z", 0]]',
                "invalide",
            ),
            ('[[autre]]\nterme = "x"', "aucune table"),
        ],
    )
    def test_message_explicite(
        self, tmp_path: Path, contenu: str, attendu: str
    ) -> None:
        chemin = tmp_path / "seed.toml"
        _ = chemin.write_text(contenu, encoding="utf-8")

        with pytest.raises(ValueError, match=attendu):
            _ = load_seed(chemin)

    def test_fichier_absent(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            _ = load_seed(tmp_path / "absent.toml")
