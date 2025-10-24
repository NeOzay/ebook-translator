"""
Tests pour la correction des erreurs de fragment_count.

Ce module teste le système de correction pour les erreurs de comptage
de séparateurs </> dans les traductions.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock

from ebook_translator.checks import FragmentCountCheck, ValidationContext
from ebook_translator.segment import Chunk


@pytest.fixture
def mock_llm():
    """LLM mock pour tests."""
    llm = Mock()
    llm.render_prompt = Mock(return_value="mocked_prompt")
    return llm


@pytest.fixture
def mock_chunk():
    """Chunk mock pour tests."""
    chunk = Mock(spec=Chunk)
    chunk.index = 0
    chunk.file_range = []
    return chunk


class TestFragmentCountValidation:
    """Tests de validation du comptage de fragments."""

    def test_text_continu_valide(self, mock_chunk, mock_llm):
        """Test : texte continu sans séparateur (valide)."""
        check = FragmentCountCheck()

        context = ValidationContext(
            chunk=mock_chunk,
            translated_texts={0: "Bonjour le monde"},
            original_texts={0: "Hello world"},
            llm=mock_llm,
            target_language="fr",
            phase="initial",
            max_retries=2,
        )

        result = check.validate(context)

        assert result.is_valid is True
        assert result.check_name == "fragment_count"
        assert result.error_message is None

    def test_text_continu_invalide_separateurs_ajoutes(self, mock_chunk, mock_llm):
        """Test : texte continu avec séparateurs ajoutés par erreur (invalide)."""
        check = FragmentCountCheck()

        context = ValidationContext(
            chunk=mock_chunk,
            translated_texts={0: "Bonjour</>le</>monde"},  # 2 séparateurs ajoutés
            original_texts={0: "Hello world"},  # 0 séparateur
            llm=mock_llm,
            target_language="fr",
            phase="initial",
            max_retries=2,
        )

        result = check.validate(context)

        assert result.is_valid is False
        assert "Séparateurs attendus: 0" in result.error_message
        assert "Séparateurs reçus: 2" in result.error_message
        assert "Texte continu" in result.error_message

    def test_text_fragmente_valide(self, mock_chunk, mock_llm):
        """Test : texte avec 1 séparateur (valide)."""
        check = FragmentCountCheck()

        context = ValidationContext(
            chunk=mock_chunk,
            translated_texts={0: "Bonjour</>le monde"},
            original_texts={0: "Hello</>world"},
            llm=mock_llm,
            target_language="fr",
            phase="initial",
            max_retries=2,
        )

        result = check.validate(context)

        assert result.is_valid is True

    def test_text_fragmente_invalide_separateur_manquant(self, mock_chunk, mock_llm):
        """Test : texte avec séparateur manquant (invalide)."""
        check = FragmentCountCheck()

        context = ValidationContext(
            chunk=mock_chunk,
            translated_texts={0: "Bonjour le monde"},  # 0 séparateur
            original_texts={0: "Hello</>world"},  # 1 séparateur
            llm=mock_llm,
            target_language="fr",
            phase="initial",
            max_retries=2,
        )

        result = check.validate(context)

        assert result.is_valid is False
        assert "Séparateurs attendus: 1" in result.error_message
        assert "Séparateurs reçus: 0" in result.error_message
        assert "Texte fragmenté" in result.error_message

    def test_text_fragmente_invalide_trop_separateurs(self, mock_chunk, mock_llm):
        """Test : texte avec trop de séparateurs (invalide)."""
        check = FragmentCountCheck()

        context = ValidationContext(
            chunk=mock_chunk,
            translated_texts={0: "Bonjour</>le</>monde"},  # 2 séparateurs
            original_texts={0: "Hello</>world"},  # 1 séparateur
            llm=mock_llm,
            target_language="fr",
            phase="initial",
            max_retries=2,
        )

        result = check.validate(context)

        assert result.is_valid is False
        assert "Séparateurs attendus: 1" in result.error_message
        assert "Séparateurs reçus: 2" in result.error_message


class TestFragmentCountCorrection:
    """Tests de correction des erreurs de fragments."""

    def test_correction_parameters_text_continu(self, mock_chunk):
        """Test : paramètres passés au template pour texte continu."""
        check = FragmentCountCheck()

        # Mock LLM avec render_prompt qui capture les paramètres
        mock_llm = Mock()
        captured_params = {}

        def capture_render_prompt(template_name, **kwargs):
            captured_params.update(kwargs)
            return "mocked_prompt"

        mock_llm.render_prompt = Mock(side_effect=capture_render_prompt)

        # Mock query pour retourner une traduction correcte
        mock_llm.query = Mock(return_value="Bonjour le monde\n[=[END]=]")

        context = ValidationContext(
            chunk=mock_chunk,
            translated_texts={0: "Bonjour</>le monde"},  # 1 séparateur (erreur)
            original_texts={0: "Hello world"},  # 0 séparateur
            llm=mock_llm,
            target_language="fr",
            phase="initial",
            max_retries=2,
        )

        # Créer error_data comme si validate() l'avait fait
        result = check.validate(context)
        assert not result.is_valid

        # Appeler correct()
        corrected = check.correct(context, result.error_data)

        # Vérifier paramètres passés au template
        assert captured_params["original_text"] == "Hello world"
        assert captured_params["incorrect_translation"] == "Bonjour</>le monde"
        assert captured_params["expected_separators"] == 0
        assert captured_params["actual_separators"] == 1
        assert captured_params["target_language"] == "fr"

    def test_correction_parameters_text_fragmente(self, mock_chunk):
        """Test : paramètres passés au template pour texte fragmenté."""
        check = FragmentCountCheck()

        mock_llm = Mock()
        captured_params = {}

        def capture_render_prompt(template_name, **kwargs):
            captured_params.update(kwargs)
            return "mocked_prompt"

        mock_llm.render_prompt = Mock(side_effect=capture_render_prompt)
        mock_llm.query = Mock(return_value="Bonjour</>le monde\n[=[END]=]")

        context = ValidationContext(
            chunk=mock_chunk,
            translated_texts={0: "Bonjour le monde"},  # 0 séparateur (erreur)
            original_texts={0: "Hello</>world"},  # 1 séparateur
            llm=mock_llm,
            target_language="fr",
            phase="initial",
            max_retries=2,
        )

        result = check.validate(context)
        assert not result.is_valid

        corrected = check.correct(context, result.error_data)

        # Vérifier paramètres
        assert captured_params["original_text"] == "Hello</>world"
        assert captured_params["expected_separators"] == 1
        assert captured_params["actual_separators"] == 0

    def test_correction_successful(self, mock_chunk):
        """Test : correction réussie (LLM retourne bon nombre de séparateurs)."""
        check = FragmentCountCheck()

        mock_llm = Mock()
        mock_llm.render_prompt = Mock(return_value="mocked_prompt")
        # LLM corrige l'erreur
        mock_llm.query = Mock(return_value="Bonjour</>le monde\n[=[END]=]")

        context = ValidationContext(
            chunk=mock_chunk,
            translated_texts={0: "Bonjour le monde"},  # 0 séparateur (erreur)
            original_texts={0: "Hello</>world"},  # 1 séparateur
            llm=mock_llm,
            target_language="fr",
            phase="initial",
            max_retries=2,
        )

        result = check.validate(context)
        corrected = check.correct(context, result.error_data)

        # La correction devrait contenir 1 séparateur
        assert corrected[0] == "Bonjour</>le monde"

    def test_correction_failed_still_wrong(self, mock_chunk):
        """Test : correction échouée (LLM retourne toujours mauvais nombre)."""
        check = FragmentCountCheck()

        mock_llm = Mock()
        mock_llm.render_prompt = Mock(return_value="mocked_prompt")
        # LLM ne corrige PAS l'erreur
        mock_llm.query = Mock(return_value="Bonjour le monde\n[=[END]=]")

        context = ValidationContext(
            chunk=mock_chunk,
            translated_texts={0: "Bonjour le monde"},  # 0 séparateur
            original_texts={0: "Hello</>world"},  # 1 séparateur
            llm=mock_llm,
            target_language="fr",
            phase="initial",
            max_retries=2,
        )

        result = check.validate(context)
        corrected = check.correct(context, result.error_data)

        # La correction devrait garder l'ancienne traduction (incorrecte)
        # car le LLM n'a pas réussi à corriger
        assert corrected[0] == "Bonjour le monde"


class TestFragmentCountErrorMessages:
    """Tests des messages d'erreur."""

    def test_error_message_text_continu(self, mock_chunk, mock_llm):
        """Test : message d'erreur pour texte continu."""
        check = FragmentCountCheck()

        context = ValidationContext(
            chunk=mock_chunk,
            translated_texts={0: "Bonjour</>le monde"},
            original_texts={0: "Hello world"},
            llm=mock_llm,
            target_language="fr",
            phase="initial",
            max_retries=2,
        )

        result = check.validate(context)

        assert "Texte continu" in result.error_message
        assert "Séparateurs attendus: 0" in result.error_message
        assert "Séparateurs reçus: 1" in result.error_message

    def test_error_message_text_fragmente(self, mock_chunk, mock_llm):
        """Test : message d'erreur pour texte fragmenté."""
        check = FragmentCountCheck()

        context = ValidationContext(
            chunk=mock_chunk,
            translated_texts={0: "Bonjour</>le</>monde"},
            original_texts={0: "Hello</>world"},
            llm=mock_llm,
            target_language="fr",
            phase="initial",
            max_retries=2,
        )

        result = check.validate(context)

        assert "Texte fragmenté" in result.error_message
        assert "Séparateurs attendus: 1" in result.error_message
        assert "Séparateurs reçus: 2" in result.error_message

    def test_error_message_multiple_errors(self, mock_chunk, mock_llm):
        """Test : message d'erreur avec plusieurs lignes incorrectes."""
        check = FragmentCountCheck()

        context = ValidationContext(
            chunk=mock_chunk,
            translated_texts={
                0: "Bonjour</>le monde",  # Erreur : 1 séparateur au lieu de 0
                1: "Salut",  # Erreur : 0 séparateur au lieu de 1
            },
            original_texts={
                0: "Hello world",
                1: "Hi</>there",
            },
            llm=mock_llm,
            target_language="fr",
            phase="initial",
            max_retries=2,
        )

        result = check.validate(context)

        assert "incorrect sur 2 ligne(s)" in result.error_message
        assert "ligne 0" in result.error_message
