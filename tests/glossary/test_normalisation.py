"""Normalisation des clés du glossaire.

Une clé normalisée sur la seule casse scinde un terme en autant d'entrées que le
livre — ou le modèle — emploie de graphies. Mesuré sur un tome complet :
`Adventurers’ Association` existait sous deux clés, poids 10 et 8, sans qu'aucune
des deux distributions n'atteigne ce que leur somme aurait donné.

Ces tests portent d'abord sur la fonction de normalisation elle-même — ce qu'elle
fusionne doit être fusionné, et ce qu'elle distingue doit rester distinct :
dépouiller les diacritiques confondrait des termes réellement différents en
langue cible. Ils vérifient ensuite que le glossaire s'en sert de bout en bout,
y compris sur les caches déjà écrits, dont les entrées scindées doivent se
recoller au chargement.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ebook_translator.glossary import (
    Glossary,
    converged_weight,
    normalize_for_matching,
)
from template.phase.glossary_models import LLMTermeGlossary

_TERME_TYPO = "Adventurers’ Association"
"""Graphie du livre : apostrophe typographique."""

_TERME_DROIT = "Adventurers' Association"
"""Graphie concurrente émise par le modèle : apostrophe droite."""

_TRADUCTION = "Association des Aventuriers"


def _entree(terme: str) -> LLMTermeGlossary:
    """Entrée de glossaire telle que produite par `LLMGlossaryModel.build()`.

    Args:
        terme: Terme source, dans la graphie où le modèle l'a émis.

    Returns:
        L'entrée correspondante.
    """
    return {
        "terme": terme,
        "type": "organisation",
        "sexe": "f",
        "proposition_traduction": _TRADUCTION,
    }


class TestFamillesFusionnees:
    """Variantes typographiques qui doivent produire la même clé."""

    @pytest.mark.parametrize(
        ("gauche", "droite"),
        [
            pytest.param(
                "Adventurers’ Association",
                "Adventurers' Association",
                id="apostrophe-typographique",
            ),
            pytest.param("dontʼt", "dont't", id="apostrophe-modificatrice"),
            pytest.param("demi‑dieu", "demi-dieu", id="trait-union-insecable"),
            pytest.param("Nord–Sud", "Nord-Sud", id="tiret-demi-cadratin"),
            pytest.param("Nord—Sud", "Nord-Sud", id="tiret-cadratin"),
            pytest.param("«Cité»", '"Cité"', id="guillemets-francais"),
            pytest.param("“Cité”", '"Cité"', id="guillemets-courbes"),
            pytest.param(
                "Cour des Miracles", "Cour des Miracles", id="espace-insecable"
            ),
            pytest.param("Guilde​des", "Guildedes", id="largeur-nulle"),
            pytest.param(
                "Guilde des  Ombres", "Guilde des Ombres", id="espaces-multiples"
            ),
            pytest.param("Guilde des\nOmbres", "Guilde des Ombres", id="retour-ligne"),
            pytest.param("  Guilde  ", "Guilde", id="blancs-de-bord"),
            pytest.param("ＡＢ", "ab", id="pleine-chasse"),
            pytest.param("Et…", "Et...", id="ellipse"),
        ],
    )
    def test_meme_cle(self, gauche: str, droite: str) -> None:
        assert normalize_for_matching(gauche) == normalize_for_matching(droite)

    def test_casse_ignoree(self) -> None:
        assert normalize_for_matching("MATRIX") == normalize_for_matching("matrix")


class TestDistinctionsPreservees:
    """Ce que la normalisation ne doit surtout pas confondre."""

    @pytest.mark.parametrize(
        ("gauche", "droite"),
        [
            pytest.param("côte", "cote", id="diacritique-francais"),
            pytest.param("Straße", "Strasse", id="eszett-allemand"),
            pytest.param("Guilde", "Guildes", id="pluriel"),
            pytest.param("demi-dieu", "demi dieu", id="trait-union-vs-espace"),
        ],
    )
    def test_cles_distinctes(self, gauche: str, droite: str) -> None:
        assert normalize_for_matching(gauche) != normalize_for_matching(droite)


class TestForme:
    """Forme exacte de la clé produite."""

    def test_cas_de_la_dette(self) -> None:
        """Le cas mesuré qui a motivé le chantier."""
        assert normalize_for_matching("Adventurers’ Association") == (
            "adventurers' association"
        )

    def test_idempotente(self) -> None:
        """Renormaliser une clé ne la change plus.

        La propriété n'est pas cosmétique : les clés déjà normalisées d'un cache
        repassent par la fonction au rechargement.
        """
        cle = normalize_for_matching("« Adventurers’ Association »")
        assert normalize_for_matching(cle) == cle

    def test_chaine_vide(self) -> None:
        assert normalize_for_matching("") == ""

    def test_invisibles_seuls(self) -> None:
        """Un terme réduit à des invisibles ne laisse rien derrière lui."""
        assert normalize_for_matching("​﻿­") == ""


class TestApprentissage:
    """Le cas de la dette, rejoué depuis `learn`.

    Le décompte plafonne à `converged_weight()` : `learn` gèle un terme dès la
    confiance haute atteinte. Ce n'est pas le cumul brut qui se mesure ici, mais
    ce que le fractionnement coûtait — deux distributions devant chacune franchir
    le seuil, là où leurs émissions réunies le franchissent une fois.
    """

    def test_les_deux_graphies_alimentent_une_seule_entree(self) -> None:
        emissions = converged_weight()
        g = Glossary()
        for _ in range(emissions - 2):
            g.learn(_entree(_TERME_TYPO))
        for _ in range(2):
            g.learn(_entree(_TERME_DROIT))

        assert len(g) == 1
        entry = g.get_translation(_TERME_TYPO)
        assert entry is not None
        assert entry["weight"] == emissions

    def test_la_fusion_fait_converger(self) -> None:
        """Séparées, aucune des deux graphies n'atteignait le seuil."""
        emissions = converged_weight()
        g = Glossary()
        for _ in range(emissions - 2):
            g.learn(_entree(_TERME_TYPO))
        for _ in range(2):
            g.learn(_entree(_TERME_DROIT))

        entry = g.get_translation(_TERME_TYPO)
        assert entry is not None
        assert entry["confidence"] == "high"

    def test_graphie_majoritaire_restituee(self) -> None:
        """Le livre emploie la forme typographique : c'est elle qui ressort."""
        emissions = converged_weight()
        g = Glossary()
        for _ in range(emissions - 2):
            g.learn(_entree(_TERME_TYPO))
        for _ in range(2):
            g.learn(_entree(_TERME_DROIT))

        entry = g.get_translation(_TERME_TYPO)
        assert entry is not None
        assert entry["terme"] == _TERME_TYPO

    def test_terme_retrouve_dans_le_bloc(self) -> None:
        """La clé a perdu son apostrophe typographique, le texte du bloc non."""
        g = Glossary()
        for _ in range(5):
            g.learn(_entree(_TERME_TYPO))

        collectees = g.collect_entry(f"the {_TERME_TYPO} sent a runner")

        assert [e["terme"] for e in collectees] == [_TERME_TYPO]

    def test_terme_retrouve_dans_l_autre_graphie(self) -> None:
        """Un bloc écrit dans la graphie concurrente reste apparié."""
        g = Glossary()
        for _ in range(5):
            g.learn(_entree(_TERME_TYPO))

        collectees = g.collect_entry(f"the {_TERME_DROIT} sent a runner")

        assert [e["terme"] for e in collectees] == [_TERME_TYPO]


class TestCleVide:
    """Un terme qui ne survit pas à la normalisation n'entre pas.

    `text.count("")` vaut `len(text) + 1` : une clé vide serait trouvée dans
    tous les blocs, et remonterait en tête du tri par occurrences pour un terme
    qui n'existe pas.
    """

    def test_terme_invisible_ecarte(self) -> None:
        g = Glossary()
        g.learn(
            {
                "terme": "​",
                "type": "objet",
                "sexe": "nc",
                "proposition_traduction": "fantôme",
            }
        )

        assert len(g) == 0

    def test_pas_de_terme_fantome_dans_la_collecte(self) -> None:
        g = Glossary()
        for _ in range(3):
            g.learn(
                {
                    "terme": "​",
                    "type": "objet",
                    "sexe": "nc",
                    "proposition_traduction": "fantôme",
                }
            )

        assert g.collect_entry("un texte qui ne contient pas ce terme") == []
        assert g.collect_entry_with_conflicts("un texte quelconque") == []

    def test_proposition_vide_ecartee(self) -> None:
        """Une entrée sans traduction ne pondère rien."""
        g = Glossary()
        g.learn(
            {
                "terme": "Guilde",
                "type": "organisation",
                "sexe": "f",
                "proposition_traduction": "   ",
            }
        )

        assert len(g) == 0

    def test_entree_user_vide_refusee(self) -> None:
        """Une saisie humaine se signale, là où le modèle est écarté en silence."""
        with pytest.raises(ValueError, match="normalisé"):
            _ = Glossary().add_user_translation(
                "​", "Fantôme", sexe="nc", terme_type="objet"
            )

    def test_cache_portant_une_cle_vide_ignore(self, tmp_path: Path) -> None:
        chemin = tmp_path / "glossary.json"
        _ = chemin.write_text(
            json.dumps(
                {
                    "glossary": {
                        "": {
                            "translations": {"fantôme": 9},
                            "term_types": {"objet": 9},
                            "sexes": {"nc": 9},
                        }
                    },
                    "user": {},
                }
            ),
            encoding="utf-8",
        )

        assert len(Glossary(chemin)) == 0


class TestGraphieMemorisee:
    """La graphie part telle quelle dans un prompt où un terme tient sur une ligne."""

    def test_terme_coupe_par_la_mise_en_page(self) -> None:
        g = Glossary()
        g.learn(_entree("Guilde des\nOmbres"))

        entry = g.get_translation("guilde des ombres")
        assert entry is not None
        assert entry["terme"] == "Guilde des Ombres"

    def test_entree_user_coupee(self) -> None:
        g = Glossary().add_user_translation(
            "Guilde des\nOmbres", "Guilde", sexe="f", terme_type="organisation"
        )

        collectees = g.collect_entry("la guilde des ombres approche")

        assert [e["terme"] for e in collectees] == ["Guilde des Ombres"]


class TestLectureParGraphie:
    """Les lectures acceptent la graphie que l'appelant a sous la main."""

    def test_get_translation_normalise_son_argument(self) -> None:
        g = Glossary()
        for _ in range(3):
            g.learn(_entree(_TERME_TYPO))

        assert g.get_translation(_TERME_TYPO) is not None
        assert g.get_translation(_TERME_DROIT) is not None

    def test_get_translations_until_confidence_normalise_son_argument(self) -> None:
        g = Glossary()
        g.learn(_entree(_TERME_TYPO))
        g.learn(_entree(_TERME_DROIT))

        assert (
            g.get_translations_until_confidence(_TERME_TYPO, confidence=1) is not None
        )


class TestFusionDesCaches:
    """Un cache écrit avant la normalisation porte les deux entrées scindées.

    Elles doivent se recoller au chargement : la fusion est le geste de
    migration, il n'existe pas d'outil séparé.
    """

    @staticmethod
    def _cache_scinde(chemin: Path) -> None:
        """Écrit le cache tel que la dette l'a mesuré.

        Args:
            chemin: Fichier JSON à écrire.
        """
        _ = chemin.write_text(
            json.dumps(
                {
                    "glossary": {
                        "adventurers’ association": {
                            "translations": {_TRADUCTION.lower(): 10},
                            "term_types": {"organisation": 10},
                            "sexes": {"f": 10},
                            "source_casing": {_TERME_TYPO: 10},
                        },
                        "adventurers' association": {
                            "translations": {_TRADUCTION.lower(): 8},
                            "term_types": {"organisation": 8},
                            "sexes": {"f": 8},
                            "source_casing": {_TERME_DROIT: 8},
                        },
                    },
                    "user": {},
                }
            ),
            encoding="utf-8",
        )

    def test_une_seule_entree_apres_chargement(self, tmp_path: Path) -> None:
        chemin = tmp_path / "glossary.json"
        self._cache_scinde(chemin)

        assert len(Glossary(chemin)) == 1

    def test_les_poids_s_additionnent(self, tmp_path: Path) -> None:
        """18 émissions valent 18, pas 10 et 8 séparément."""
        chemin = tmp_path / "glossary.json"
        self._cache_scinde(chemin)

        entry = Glossary(chemin).get_translation(_TERME_TYPO)

        assert entry is not None
        assert entry["weight"] == 18

    def test_la_fusion_fait_converger(self, tmp_path: Path) -> None:
        """Ce que le fractionnement empêchait : atteindre la confiance haute."""
        chemin = tmp_path / "glossary.json"
        self._cache_scinde(chemin)

        entry = Glossary(chemin).get_translation(_TERME_TYPO)

        assert entry is not None
        assert entry["confidence"] == "high"

    def test_graphies_des_deux_cles_fusionnees(self, tmp_path: Path) -> None:
        """Les deux entrées apportent leur graphie ; la majoritaire l'emporte."""
        chemin = tmp_path / "glossary.json"
        self._cache_scinde(chemin)

        entry = Glossary(chemin).get_translation(_TERME_TYPO)

        assert entry is not None
        assert entry["terme"] == _TERME_TYPO

    def test_propositions_scindees_fusionnees(self, tmp_path: Path) -> None:
        """Le fractionnement frappe aussi le côté cible."""
        chemin = tmp_path / "glossary.json"
        _ = chemin.write_text(
            json.dumps(
                {
                    "glossary": {
                        "guilde": {
                            "translations": {"l’ancien": 6, "l'ancien": 4},
                            "term_types": {"organisation": 10},
                            "sexes": {"f": 10},
                        }
                    },
                    "user": {},
                }
            ),
            encoding="utf-8",
        )

        detail = Glossary(chemin).get_translations_until_confidence(
            "guilde", confidence=1
        )

        assert detail is not None
        assert len(detail["traductions"]) == 1
        assert detail["traductions"][0][1] == 10

    def test_aller_retour_conserve_la_graphie(self, tmp_path: Path) -> None:
        """Un cache écrit par cette version retrouve sa graphie au rechargement."""
        chemin = tmp_path / "glossary.json"
        g = Glossary()
        for _ in range(3):
            g.learn(_entree(_TERME_TYPO))
        g.save(chemin)

        entry = Glossary(chemin).get_translation(_TERME_TYPO)

        assert entry is not None
        assert entry["terme"] == _TERME_TYPO
