"""
Tests pour le module de validation du glossaire.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from io import StringIO

from ebook_translator.glossary import Glossary
from ebook_translator.pipeline.glossary_validator import GlossaryValidator


@pytest.fixture
def glossary_with_conflicts(tmp_path: Path) -> Glossary:
    """Crée un glossaire avec des conflits terminologiques."""
    glossary = Glossary(cache_path=tmp_path / "glossary.json")

    # Ajouter des termes sans conflit
    glossary.learn("Sakamoto", "Sakamoto")
    glossary.learn("Sakamoto", "Sakamoto")
    glossary.learn("DNA", "ADN")
    glossary.learn("DNA", "ADN")
    glossary.learn("DNA", "ADN")

    # Ajouter un terme avec conflit (traductions équilibrées)
    glossary.learn("Matrix", "Matrice")
    glossary.learn("Matrix", "Matrice")
    glossary.learn("Matrix", "Système")
    glossary.learn("Matrix", "Système")

    return glossary


@pytest.fixture
def glossary_no_conflicts(tmp_path: Path) -> Glossary:
    """Crée un glossaire sans conflits."""
    glossary = Glossary(cache_path=tmp_path / "glossary.json")

    glossary.learn("Sakamoto", "Sakamoto")
    glossary.learn("Sakamoto", "Sakamoto")
    glossary.learn("DNA", "ADN")
    glossary.learn("DNA", "ADN")
    glossary.learn("Matrix", "Matrice")
    glossary.learn("Matrix", "Matrice")
    glossary.learn("Matrix", "Matrice")

    return glossary


class TestGlossaryValidator:
    """Tests pour GlossaryValidator."""

    def test_init(self, glossary_no_conflicts: Glossary):
        """Test l'initialisation du validateur."""
        validator = GlossaryValidator(glossary_no_conflicts)
        assert validator.glossary is glossary_no_conflicts

    def test_display_statistics(self, glossary_with_conflicts: Glossary, caplog):
        """Test l'affichage des statistiques."""
        validator = GlossaryValidator(glossary_with_conflicts)

        with caplog.at_level("INFO"):
            validator._display_statistics()

        # Vérifier que les statistiques sont affichées
        assert "STATISTIQUES DU GLOSSAIRE" in caplog.text
        assert "Termes appris: 3" in caplog.text
        assert "Termes en conflit: 1" in caplog.text

    def test_display_conflicts(self, glossary_with_conflicts: Glossary, caplog):
        """Test l'affichage des conflits."""
        validator = GlossaryValidator(glossary_with_conflicts)
        conflicts = glossary_with_conflicts.get_conflicts()

        with caplog.at_level("INFO"):
            validator._display_conflicts(conflicts)

        # Vérifier que le conflit Matrix est affiché
        assert "Matrix" in caplog.text
        assert "Matrice" in caplog.text
        assert "Système" in caplog.text

    def test_auto_resolve_conflicts(self, glossary_with_conflicts: Glossary):
        """Test la résolution automatique des conflits."""
        validator = GlossaryValidator(glossary_with_conflicts)
        conflicts = glossary_with_conflicts.get_conflicts()

        # Avant résolution
        assert "Matrix" in conflicts
        assert glossary_with_conflicts._validated.get("Matrix") is None

        # Résolution automatique
        validator._auto_resolve_conflicts(conflicts)

        # Après résolution
        assert glossary_with_conflicts._validated.get("Matrix") is not None
        # Devrait choisir "Matrice" ou "Système" (le plus fréquent, ici égal mais déterministe)
        assert glossary_with_conflicts._validated["Matrix"] in ["Matrice", "Système"]

    def test_validate_interactive_no_conflicts_with_confirmation(
        self, glossary_no_conflicts: Glossary
    ):
        """Test validation interactive sans conflits avec confirmation utilisateur."""
        validator = GlossaryValidator(glossary_no_conflicts)

        # Simuler confirmation utilisateur (réponse 'o')
        with patch("builtins.input", return_value="o"):
            result = validator.validate_interactive(auto_resolve=False)

        assert result is True

    def test_validate_interactive_no_conflicts_cancelled(
        self, glossary_no_conflicts: Glossary
    ):
        """Test validation interactive annulée par l'utilisateur."""
        validator = GlossaryValidator(glossary_no_conflicts)

        # Simuler annulation (réponse 'n')
        with patch("builtins.input", return_value="n"):
            result = validator.validate_interactive(auto_resolve=False)

        assert result is False

    def test_validate_interactive_with_conflicts_auto_resolve(
        self, glossary_with_conflicts: Glossary
    ):
        """Test validation avec conflits et résolution automatique."""
        validator = GlossaryValidator(glossary_with_conflicts)

        # Auto-résolution (pas de prompt utilisateur)
        result = validator.validate_interactive(auto_resolve=True)

        assert result is True
        # Le conflit Matrix devrait être résolu
        assert glossary_with_conflicts._validated.get("Matrix") is not None

    def test_validate_interactive_with_conflicts_manual_choice(
        self, glossary_with_conflicts: Glossary
    ):
        """Test validation avec choix manuel de traduction."""
        validator = GlossaryValidator(glossary_with_conflicts)

        # Récupérer les traductions conflictuelles AVANT résolution
        conflicts_before = glossary_with_conflicts.get_conflicts()
        translations = list(conflicts_before["Matrix"])

        # Simuler choix manuel : choisir option 1 (Matrice)
        with patch("builtins.input", side_effect=["1"]):
            result = validator.validate_interactive(auto_resolve=False)

        assert result is True
        # Matrix devrait être validé avec la première option
        assert glossary_with_conflicts._validated["Matrix"] == translations[0]

    def test_validate_interactive_with_conflicts_skip_and_auto(
        self, glossary_with_conflicts: Glossary
    ):
        """Test validation avec skip (résolution auto à la fin)."""
        validator = GlossaryValidator(glossary_with_conflicts)

        # Simuler skip ('s')
        with patch("builtins.input", return_value="s"):
            result = validator.validate_interactive(auto_resolve=False)

        assert result is True
        # Le conflit devrait être résolu automatiquement
        assert glossary_with_conflicts._validated.get("Matrix") is not None

    def test_validate_interactive_quit(self, glossary_with_conflicts: Glossary):
        """Test validation avec quit utilisateur."""
        validator = GlossaryValidator(glossary_with_conflicts)

        # Simuler quit ('q')
        with patch("builtins.input", return_value="q"):
            result = validator.validate_interactive(auto_resolve=False)

        assert result is False

    def test_validate_interactive_invalid_then_valid(
        self, glossary_with_conflicts: Glossary
    ):
        """Test validation avec entrée invalide puis valide."""
        validator = GlossaryValidator(glossary_with_conflicts)

        # Simuler entrée invalide puis valide
        with patch("builtins.input", side_effect=["invalid", "999", "1"]):
            result = validator.validate_interactive(auto_resolve=False)

        assert result is True

    def test_export_summary_no_conflicts(self, glossary_no_conflicts: Glossary):
        """Test export du résumé sans conflits."""
        validator = GlossaryValidator(glossary_no_conflicts)

        summary = validator.export_summary()

        assert "RÉSUMÉ DU GLOSSAIRE VALIDÉ" in summary
        assert "Termes appris: 3" in summary
        assert "Sakamoto → Sakamoto" in summary
        assert "DNA → ADN" in summary
        assert "Matrix → Matrice" in summary

    def test_export_summary_with_conflicts(self, glossary_with_conflicts: Glossary):
        """Test export du résumé avec conflits non résolus."""
        validator = GlossaryValidator(glossary_with_conflicts)

        summary = validator.export_summary()

        assert "RÉSUMÉ DU GLOSSAIRE VALIDÉ" in summary
        assert "Termes appris: 3" in summary
        assert "ATTENTION: Conflits non résolus" in summary
        assert "Matrix" in summary

    def test_display_sample_terms_limited(self, tmp_path: Path):
        """Test affichage d'échantillon de termes avec limite."""
        glossary = Glossary(cache_path=tmp_path / "glossary.json")

        # Ajouter beaucoup de termes haute confiance
        for i in range(20):
            term = f"Term{i}"
            translation = f"Terme{i}"
            for _ in range(5):  # Haute confiance
                glossary.learn(term, translation)

        validator = GlossaryValidator(glossary)

        with patch("ebook_translator.pipeline.glossary_validator.logger") as mock_logger:
            validator._display_sample_terms(max_terms=10)

            # Vérifier que seulement 10 termes + message "et X autres" sont affichés
            call_args = [str(call) for call in mock_logger.info.call_args_list]
            log_text = " ".join(call_args)

            # Au moins 10 termes affichés
            term_count = sum(1 for call in call_args if "→" in str(call))
            assert term_count == 10

            # Message "et X autres" présent
            assert "autre(s) terme(s)" in log_text


class TestConfirmValidation:
    """Tests pour la confirmation de validation."""

    def test_confirm_validation_yes_variants(self, glossary_no_conflicts: Glossary):
        """Test confirmation avec différentes variantes de 'oui'."""
        validator = GlossaryValidator(glossary_no_conflicts)

        for response in ["", "o", "oui", "y", "yes"]:
            with patch("builtins.input", return_value=response):
                result = validator._confirm_validation()
                assert result is True

    def test_confirm_validation_no_variants(self, glossary_no_conflicts: Glossary):
        """Test confirmation avec différentes variantes de 'non'."""
        validator = GlossaryValidator(glossary_no_conflicts)

        for response in ["n", "non", "no"]:
            with patch("builtins.input", return_value=response):
                result = validator._confirm_validation()
                assert result is False

    def test_confirm_validation_invalid_then_valid(
        self, glossary_no_conflicts: Glossary
    ):
        """Test confirmation avec entrée invalide puis valide."""
        validator = GlossaryValidator(glossary_no_conflicts)

        with patch("builtins.input", side_effect=["invalid", "maybe", "o"]):
            result = validator._confirm_validation()

        assert result is True

    def test_confirm_validation_keyboard_interrupt(
        self, glossary_no_conflicts: Glossary
    ):
        """Test confirmation avec interruption clavier."""
        validator = GlossaryValidator(glossary_no_conflicts)

        with patch("builtins.input", side_effect=KeyboardInterrupt):
            result = validator._confirm_validation()

        assert result is False
