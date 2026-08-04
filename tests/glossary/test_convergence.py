"""Seuils de convergence du glossaire.

Ces deux fonctions décrivent le mécanisme dont dépendent le prompt de la phase
(`glossary_existing_block.jinja`) et l'auditeur : un terme n'est réinjecté qu'à
partir d'un certain poids, et n'en sort qu'à un poids plus élevé encore.
"""

from ebook_translator.glossary import (
    DEFAULT_MIN_REINJECTION_WEIGHT,
    confidence_level,
    converged_weight,
)


class TestConfidenceLevel:
    """Niveau de confiance d'une distribution."""

    def test_unanimite_faible_reste_basse(self) -> None:
        """Le facteur de masse interdit qu'une seule émission fasse autorité."""
        assert confidence_level([1]) == "low"

    def test_unanimite_suffisante_passe_haute(self) -> None:
        assert confidence_level([converged_weight()]) == "high"

    def test_desaccord_abaisse_le_niveau(self) -> None:
        poids = converged_weight()
        assert confidence_level([poids // 2 + 1, poids // 2]) != "high"

    def test_distribution_vide_reste_basse(self) -> None:
        assert confidence_level([]) == "low"


class TestConvergedWeight:
    """Poids unanime minimal pour la confiance haute."""

    def test_vaut_le_premier_poids_classe_haut(self) -> None:
        seuil = converged_weight()

        assert confidence_level([seuil]) == "high"
        assert confidence_level([seuil - 1]) != "high"

    def test_exige_plus_que_le_seuil_de_reinjection(self) -> None:
        """Un terme est montré au LLM bien avant d'être considéré comme stable."""
        assert converged_weight() > DEFAULT_MIN_REINJECTION_WEIGHT

    def test_recherche_bornee(self) -> None:
        """Une borne trop basse rend la borne, sans boucler."""
        assert converged_weight(search_limit=2) == 2
