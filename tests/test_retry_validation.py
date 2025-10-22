"""
Tests pour la validation des retries de traduction.

Vérifie que validate_retry_indices détecte correctement les cas d'erreur
et accepte les cas valides.
"""

import pytest
from ebook_translator.translation.parser import validate_retry_indices


class TestValidateRetryIndices:
    """Tests pour validate_retry_indices."""

    def test_valid_exact_match(self):
        """Le retry a fourni exactement les indices demandés."""
        retry_translations = {5: "Hello", 10: "World", 15: "Test"}
        expected_indices = [5, 10, 15]

        is_valid, error_message = validate_retry_indices(
            retry_translations, expected_indices
        )

        assert is_valid is True
        assert error_message is None

    def test_valid_empty(self):
        """Cas limite : aucun indice demandé."""
        retry_translations = {}
        expected_indices = []

        is_valid, error_message = validate_retry_indices(
            retry_translations, expected_indices
        )

        assert is_valid is True
        assert error_message is None

    def test_invalid_missing_indices(self):
        """Le retry n'a pas fourni tous les indices demandés."""
        retry_translations = {5: "Hello", 10: "World"}
        expected_indices = [5, 10, 15, 20]

        is_valid, error_message = validate_retry_indices(
            retry_translations, expected_indices
        )

        assert is_valid is False
        assert error_message is not None
        assert "Toujours manquants" in error_message
        assert "<15/>" in error_message
        assert "<20/>" in error_message

    def test_invalid_extra_indices(self):
        """Le retry a fourni des indices non demandés."""
        retry_translations = {5: "Hello", 10: "World", 99: "Invalid", 100: "Extra"}
        expected_indices = [5, 10]

        is_valid, error_message = validate_retry_indices(
            retry_translations, expected_indices
        )

        assert is_valid is False
        assert error_message is not None
        assert "Indices invalides" in error_message
        assert "<99/>" in error_message
        assert "<100/>" in error_message

    def test_invalid_both_missing_and_extra(self):
        """Le retry a des indices manquants ET des indices en trop."""
        retry_translations = {5: "Hello", 99: "Invalid"}
        expected_indices = [5, 10, 15]

        is_valid, error_message = validate_retry_indices(
            retry_translations, expected_indices
        )

        assert is_valid is False
        assert error_message is not None
        # Vérifier les deux types d'erreur
        assert "Toujours manquants" in error_message
        assert "<10/>" in error_message
        assert "<15/>" in error_message
        assert "Indices invalides" in error_message
        assert "<99/>" in error_message

    def test_invalid_completely_wrong(self):
        """Le retry a fourni des indices complètement différents."""
        retry_translations = {100: "Wrong", 101: "Indices", 102: "Here"}
        expected_indices = [0, 1, 2]

        is_valid, error_message = validate_retry_indices(
            retry_translations, expected_indices
        )

        assert is_valid is False
        assert error_message is not None
        assert "Toujours manquants" in error_message
        assert "Indices invalides" in error_message

    def test_error_message_truncation(self):
        """Les listes longues sont tronquées dans le message d'erreur."""
        retry_translations = {}
        expected_indices = list(range(50))  # 50 indices manquants

        is_valid, error_message = validate_retry_indices(
            retry_translations, expected_indices
        )

        assert is_valid is False
        assert error_message is not None
        # Devrait montrer seulement les 10 premiers + indication d'autres
        assert "+40 autres" in error_message or "..." in error_message

    def test_valid_order_doesnt_matter(self):
        """L'ordre des indices n'a pas d'importance."""
        retry_translations = {15: "C", 5: "A", 10: "B"}
        expected_indices = [5, 10, 15]

        is_valid, error_message = validate_retry_indices(
            retry_translations, expected_indices
        )

        assert is_valid is True
        assert error_message is None

    def test_error_message_contains_suggestions(self):
        """Le message d'erreur contient des suggestions utiles."""
        retry_translations = {5: "Hello"}
        expected_indices = [5, 10]

        is_valid, error_message = validate_retry_indices(
            retry_translations, expected_indices
        )

        assert is_valid is False
        assert "💡 Causes possibles" in error_message
        assert "🔧 Solutions" in error_message
