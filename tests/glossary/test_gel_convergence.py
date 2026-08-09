"""Un terme convergé n'apprend plus rien.

Le prompt liste les termes convergés sous « Termes validés — NE PAS inclure »,
et le modèle les réémet malgré tout : mesuré sur un tome complet, 10 sur 11,
jusqu'à 13 réémissions pour le plus fréquent. Renforcer la consigne s'est
révélé sans effet et coûteux en rappel — le filtre est donc posé dans `learn`,
où il ne dépend pas de l'obéissance du modèle.

Ce que ces tests fixent : la convergence est un état absorbant. Ni la
confirmation ni la contradiction n'y entrent, et une entrée `user` ne corrige
pas la distribution — elle la masque.
"""

from __future__ import annotations

import pytest

from ebook_translator.glossary import Glossary, converged_weight
from template.phase.glossary_models import LLMTermeGlossary


def _proposition(traduction: str, terme: str = "flio") -> LLMTermeGlossary:
    """Émission du LLM pour un terme donné.

    Args:
        traduction: Traduction proposée.
        terme: Terme source.

    Returns:
        L'entrée telle que la phase glossaire la produit.
    """
    return {
        "terme": terme,
        "type": "personnage",
        "sexe": "m",
        "proposition_traduction": traduction,
    }


@pytest.fixture
def convergé() -> Glossary:
    """Glossaire dont le seul terme vient d'atteindre la confiance haute.

    Returns:
        Le glossaire peuplé.
    """
    glossaire = Glossary()
    for _ in range(converged_weight()):
        glossaire.learn(_proposition("Flio"))
    return glossaire


def _poids(glossaire: Glossary, terme: str = "flio") -> int:
    """Poids total accumulé par un terme.

    Args:
        glossaire: Glossaire à interroger.
        terme: Terme source, en minuscules.

    Returns:
        La somme des effectifs de ses propositions.
    """
    return sum(glossaire._glossary[terme]["translations"].values())  # pyright: ignore[reportPrivateUsage]


class TestGel:
    def test_le_terme_est_bien_convergé_au_départ(self, convergé: Glossary) -> None:
        entrée = convergé.get_translation("flio")

        assert entrée is not None
        assert entrée["confidence"] == "high"
        assert _poids(convergé) == converged_weight()

    def test_confirmation_ignorée(self, convergé: Glossary) -> None:
        """Réémettre la dominante n'ajoute pas de poids."""
        convergé.learn(_proposition("Flio"))

        assert _poids(convergé) == converged_weight()

    def test_contradiction_ignorée(self, convergé: Glossary) -> None:
        """Une proposition divergente n'entame pas la dominante.

        C'est la contrepartie assumée du gel : compter les seules divergences
        ferait chuter la confiance d'un terme pourtant stable.
        """
        convergé.learn(_proposition("Fliot"))

        entrée = convergé.get_translation("flio")
        assert entrée is not None
        assert entrée["traduction"] == "Flio"
        assert _poids(convergé) == converged_weight()

    def test_réémissions_répétées_sans_effet(self, convergé: Glossary) -> None:
        """Le cas mesuré sur le tome : 13 réémissions du terme le plus fréquent."""
        for _ in range(13):
            convergé.learn(_proposition("Flio"))

        assert _poids(convergé) == converged_weight()


class TestAvantConvergence:
    def test_un_terme_non_convergé_apprend_toujours(self) -> None:
        """Le filtre ne mord qu'une fois la confiance haute atteinte."""
        glossaire = Glossary()
        for _ in range(converged_weight() - 1):
            glossaire.learn(_proposition("Flio"))

        assert _poids(glossaire) == converged_weight() - 1

    def test_un_terme_en_conflit_apprend_toujours(self) -> None:
        """Un désaccord empêche la confiance haute, donc le gel."""
        glossaire = Glossary()
        for _ in range(converged_weight()):
            glossaire.learn(_proposition("Flio"))
            glossaire.learn(_proposition("Fliot"))

        assert _poids(glossaire) == 2 * converged_weight()


class TestMasquage:
    def test_l_entrée_user_masque_un_terme_gelé(self, convergé: Glossary) -> None:
        """L'autorité manuelle prend la main sur ce que voient les prompts.

        La vérification passe par `collect_entry`, qui alimente les prompts de
        traduction. `get_translation` ne consulte pas `_user` — sa branche
        dédiée est restée commentée — et rendrait ici la valeur apprise.
        """
        _ = convergé.add_user_translation(
            "flio", "Fliaux", sexe="m", terme_type="personnage"
        )

        retenues = convergé.collect_entry("Flio traversa la place.")

        assert [e["traduction"] for e in retenues if e["terme"] == "flio"] == ["Fliaux"]

    def test_la_distribution_apprise_est_intacte(self, convergé: Glossary) -> None:
        """Le masquage ne réécrit rien : l'entrée apprise garde sa valeur."""
        _ = convergé.add_user_translation(
            "flio", "Fliaux", sexe="m", terme_type="personnage"
        )

        apprise = convergé.get_translation("flio")
        assert apprise is not None
        assert apprise["traduction"] == "Flio"
