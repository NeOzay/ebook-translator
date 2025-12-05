"""
Tests pour la correction des erreurs de fragment_count.

Ce module teste le système de correction pour les erreurs de comptage
de séparateurs </> dans les traductions.
"""

from unittest.mock import Mock

from ebook_translator.checks import FragmentCountCheck, ValidationContext
from ebook_translator.checks.check_tests.base import FailedResult, SuccessResult


class TestFragmentCountValidation:
    """Tests de validation du comptage de fragments."""

    def test_text_continu_valide(self, val_context: ValidationContext):
        """Test : texte continu sans séparateur (valide)."""
        check = FragmentCountCheck()

        val_context.translated_texts = {0: "Bonjour le monde"}
        val_context.original_texts = {0: "Hello world"}

        result = check.validate(val_context)

        assert isinstance(result, SuccessResult)

    def test_text_continu_invalide_separateurs_ajoutes(
        self, val_context: ValidationContext
    ):
        """Test : texte continu avec séparateurs ajoutés par erreur (invalide)."""
        check = FragmentCountCheck()

        val_context.translated_texts = {
            0: "Bonjour</>le</>monde"
        }  # 2 séparateurs ajoutés
        val_context.original_texts = {0: "Hello world"}  # 0 séparateur

        result = check.validate(val_context)

        assert isinstance(result, FailedResult)

    def test_text_fragmente_valide(self, val_context: ValidationContext):
        """Test : texte avec 1 séparateur (valide)."""
        check = FragmentCountCheck()

        val_context.translated_texts = {0: "Bonjour</>le monde"}
        val_context.original_texts = {0: "Hello</>world"}

        result = check.validate(val_context)

        assert isinstance(result, SuccessResult)

    def test_text_fragmente_invalide_separateur_manquant(
        self, val_context: ValidationContext
    ):
        """Test : texte avec séparateur manquant (invalide)."""
        check = FragmentCountCheck()

        val_context.translated_texts = {0: "Bonjour le monde"}  # 0 séparateur
        val_context.original_texts = {0: "Hello</>world"}  # 1 séparateur

        result = check.validate(val_context)
        assert isinstance(result, FailedResult)
        error_message = result.error_message or ""
        assert "Séparateurs attendus: 1" in error_message
        assert "Séparateurs reçus: 0" in error_message
        assert "Texte fragmenté" in error_message

    def test_text_fragmente_invalide_trop_separateurs(
        self, val_context: ValidationContext
    ):
        """Test : texte avec trop de séparateurs (invalide)."""
        check = FragmentCountCheck()

        val_context.translated_texts = {0: "Bonjour</>le</>monde"}  # 2 séparateurs
        val_context.original_texts = {0: "Hello</>world"}  # 1 séparateur

        result = check.validate(val_context)

        assert isinstance(result, FailedResult)
        error_message = result.error_message or ""
        assert "Texte fragmenté" in error_message
        assert "Séparateurs attendus: 1" in error_message
        assert "Séparateurs reçus: 2" in error_message


class TestFragmentCountCorrection:
    """Tests de correction des erreurs de fragments."""

    def test_correction_successful(self, val_context: ValidationContext):
        """Test : correction réussie (LLM retourne bon nombre de séparateurs)."""
        check = FragmentCountCheck()

        mock_llm = Mock()
        # LLM corrige l'erreur
        mock_llm.query = Mock(return_value="Bonjour</>le monde\n[=[END]=]")

        val_context.llm = mock_llm
        val_context.translated_texts = {0: "Bonjour le monde"}  # 0 séparateur
        val_context.original_texts = {0: "Hello</>world"}  # 1 séparateur

        result = check.validate(val_context)
        assert isinstance(result, FailedResult)
        corrected = check.correct(val_context, result.error_data)

        # La correction devrait contenir 1 séparateur
        assert corrected[0] == "Bonjour</>le monde"

    def test_correction_failed_still_wrong(self, val_context: ValidationContext):
        """Test : correction échouée (LLM retourne toujours mauvais nombre)."""
        check = FragmentCountCheck()

        mock_llm = Mock()
        # LLM ne corrige PAS l'erreur
        mock_llm.query = Mock(return_value="Bonjour le monde\n[=[END]=]")
        val_context.llm = mock_llm
        val_context.translated_texts = {0: "Bonjour le monde"}  # 0 séparateur
        val_context.original_texts = {0: "Hello</>world"}  # 1 séparateur

        result = check.validate(val_context)
        assert isinstance(result, FailedResult)
        corrected = check.correct(val_context, result.error_data)

        # La correction devrait garder l'ancienne traduction (incorrecte)
        # car le LLM n'a pas réussi à corriger
        assert corrected[0] == "Bonjour le monde"


class TestFragmentCountErrorMessages:
    """Tests des messages d'erreur."""

    def test_error_message_text_continu(self, val_context: ValidationContext):
        """Test : message d'erreur pour texte continu."""
        check = FragmentCountCheck()
        val_context.translated_texts = {0: "Bonjour</>le monde"}
        val_context.original_texts = {0: "Hello world"}

        result = check.validate(val_context)
        assert isinstance(result, FailedResult)
        error_message = result.error_message or ""

        assert "Texte continu" in error_message
        assert "Séparateurs attendus: 0" in error_message
        assert "Séparateurs reçus: 1" in error_message

    def test_error_message_text_fragmente(self, val_context: ValidationContext):
        """Test : message d'erreur pour texte fragmenté."""
        check = FragmentCountCheck()

        val_context.translated_texts = {0: "Bonjour</>le</>monde"}
        val_context.original_texts = {0: "Hello</>world"}

        result = check.validate(val_context)
        assert isinstance(result, FailedResult)
        error_message = result.error_message or ""

        assert "Texte fragmenté" in error_message
        assert "Séparateurs attendus: 1" in error_message
        assert "Séparateurs reçus: 2" in error_message

    def test_error_message_multiple_errors(self, val_context: ValidationContext):
        """Test : message d'erreur avec plusieurs lignes incorrectes."""
        check = FragmentCountCheck()

        val_context.translated_texts = {
            0: "Bonjour</>le monde",  # Erreur : 1 séparateur au lieu de 0
            1: "Salut",  # Erreur : 0 séparateur au lieu de 1
        }
        val_context.original_texts = {
            0: "Hello world",
            1: "Hi</>there",
        }

        result = check.validate(val_context)
        assert isinstance(result, FailedResult)
        error_message = result.error_message or ""

        assert "incorrect sur 2 ligne(s)" in error_message
        assert "ligne 0" in error_message
