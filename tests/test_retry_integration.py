"""
Tests pour la fonction mark_lines_to_numbered du module Chunk.

Vérifie que la numérotation sélective des lignes fonctionne correctement.
"""

from unittest.mock import Mock
from ebook_translator.segment import Chunk


class TestMarkLinesToNumbered:
    """Tests spécifiques pour mark_lines_to_numbered."""

    def test_mark_subset_of_lines(self):
        """Vérifie que seules les lignes spécifiées sont numérotées."""
        # Utiliser des mocks simples pour les clés
        chunk = Chunk(
            index=0,
            body={
                Mock(index="0"): "Line 0",
                Mock(index="1"): "Line 1",
                Mock(index="2"): "Line 2",
                Mock(index="3"): "Line 3",
            },
            head=["Context before"],
            tail=["Context after"],
        )

        # Numéroter seulement les lignes 1 et 3
        result = chunk.mark_lines_to_numbered([1, 3])

        # Vérifier que le contexte est présent
        assert "Context before" in result
        assert "Context after" in result

        # Vérifier que seules les lignes 1 et 3 sont numérotées
        assert "<0/>" not in result  # Ligne 0 non numérotée
        assert "<1/>Line 1" in result  # Ligne 1 numérotée
        assert "<2/>" not in result  # Ligne 2 non numérotée
        assert "<3/>Line 3" in result  # Ligne 3 numérotée

        # Vérifier que les lignes non numérotées sont présentes
        assert "Line 0" in result
        assert "Line 2" in result

    def test_mark_empty_list(self):
        """Si aucun indice n'est fourni, aucune ligne n'est numérotée."""
        chunk = Chunk(
            index=0,
            body={
                Mock(index="0"): "Line 0",
                Mock(index="1"): "Line 1",
            },
            head=[],
            tail=[],
        )

        result = chunk.mark_lines_to_numbered([])

        # Aucune ligne ne devrait être numérotée
        assert "<0/>" not in result
        assert "<1/>" not in result

        # Mais le contenu devrait être présent
        assert "Line 0" in result
        assert "Line 1" in result
