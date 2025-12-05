"""
Tests unitaires pour la classe Chunk.

Ces tests vérifient le comportement de la classe Chunk
qui représente un segment de contenu à traduire.
"""

from unittest.mock import Mock

from ebook_translator.segmentation import Chunk


class TestChunk:
    """Tests pour la classe Chunk."""

    def test_chunk_str_format(self):
        """Vérifie le format string d'un chunk."""
        chunk = Chunk(index=0)

        # Créer des mock TagKeys
        tag_key1 = Mock()
        tag_key2 = Mock()

        chunk.head = ["Context head"]
        chunk.body = {tag_key1: "Text 1", tag_key2: "Text 2"}
        chunk.tail = ["Context tail"]

        result = str(chunk)

        # Vérifier le format
        assert "<0/>Text 1" in result
        assert "<1/>Text 2" in result
        assert "Context head" in result
        assert "Context tail" in result

    def test_chunk_str_without_context(self):
        """Vérifie le format string sans head ni tail."""
        chunk = Chunk(index=0)
        tag_key = Mock()
        chunk.body = {tag_key: "Only text"}

        result = str(chunk)

        assert "<0/>Only text" in result
        assert result.count("\n\n") >= 0  # Peut avoir des séparateurs

    def test_chunk_fetch(self):
        """Vérifie que fetch génère les bonnes tuples."""
        chunk = Chunk(index=0)

        # Créer des mocks
        page1 = Mock()
        page2 = Mock()
        tag_key1 = Mock()
        tag_key1.page = page1
        tag_key2 = Mock()
        tag_key2.page = page2

        chunk.body = {
            tag_key1: "Text 1",
            tag_key2: "Text 2",
        }

        # Récupérer les items
        items = list(chunk.fetch())

        assert len(items) == 2
        assert items[0] == (page1, tag_key1, "Text 1")
        assert items[1] == (page2, tag_key2, "Text 2")

    def test_chunk_repr(self):
        """Vérifie la représentation pour le debug."""
        chunk = Chunk(index=5)
        chunk.head = ["h1", "h2"]
        chunk.body = {Mock(): "t1", Mock(): "t2", Mock(): "t3"}
        chunk.tail = ["t1"]

        repr_str = repr(chunk)

        assert "Chunk" in repr_str
        assert "index=5" in repr_str
        assert "body_items=3" in repr_str
        assert "head_items=2" in repr_str
        assert "tail_items=1" in repr_str
