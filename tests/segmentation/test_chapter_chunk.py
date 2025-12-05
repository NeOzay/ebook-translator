"""
Tests unitaires pour le module ChapterChunk.

Ces tests vérifient le comportement des classes ChapterChunk et ChapterPartChunk,
notamment la conversion type-safe via from_chunk().
"""

from unittest.mock import Mock

from ebook_translator.htmlpage.tag_key import TagKey
from ebook_translator.segmentation import Chunk
from ebook_translator.segmentation.chapter_chunk import ChapterChunk, ChapterPartChunk


class TestChapterPartChunk:
    """Tests pour la classe ChapterPartChunk."""

    def test_from_chunk_copies_all_attributes(self):
        """Vérifie que from_chunk() copie tous les attributs de Chunk."""
        # Créer un chunk source avec tous les attributs
        chunk = Chunk(index=5, token_count=100, token_encoding="cl100k_base")
        chunk.head = {"head_key": "head_text"}
        chunk.body = {"body_key": "body_text"}
        chunk.tail = {"tail_key": "tail_text"}

        # Mock ChapterChunk
        mock_chapter = Mock(spec=ChapterChunk)

        # Conversion
        part = ChapterPartChunk.from_chunk(chunk, mock_chapter, total_parts=3)

        # Vérifier tous les attributs
        assert part.index == 5
        assert part.token_count == 100
        assert part.token_encoding == "cl100k_base"
        assert part.total_parts == 3
        assert part.chapter is mock_chapter

    def test_from_chunk_copies_dictionaries_independently(self):
        """Vérifie que les dictionnaires sont copiés indépendamment (pas de références partagées)."""
        # Créer un chunk source
        chunk = Chunk(index=0, token_encoding="cl100k_base")
        chunk.head = {"key1": "value1"}
        chunk.body = {"key2": "value2"}
        chunk.tail = {"key3": "value3"}

        mock_chapter = Mock(spec=ChapterChunk)

        # Conversion
        part = ChapterPartChunk.from_chunk(chunk, mock_chapter, total_parts=1)

        # Modifier le chunk original
        chunk.head["new_head"] = "new_value"
        chunk.body["new_body"] = "new_value"
        chunk.tail["new_tail"] = "new_value"

        # Vérifier que part n'est PAS affecté
        assert "new_head" not in part.head
        assert "new_body" not in part.body
        assert "new_tail" not in part.tail

        # Vérifier que les valeurs originales sont présentes
        assert part.head["key1"] == "value1"
        assert part.body["key2"] == "value2"
        assert part.tail["key3"] == "value3"

    def test_from_chunk_with_empty_dictionaries(self):
        """Vérifie que from_chunk() fonctionne avec des dictionnaires vides."""
        chunk = Chunk(index=0, token_count=0, token_encoding="cl100k_base")
        # head, body, tail sont vides par défaut

        mock_chapter = Mock(spec=ChapterChunk)
        part = ChapterPartChunk.from_chunk(chunk, mock_chapter, total_parts=1)

        assert len(part.head) == 0
        assert len(part.body) == 0
        assert len(part.tail) == 0

    def test_from_chunk_with_tagkey_dictionaries(self):
        """Vérifie que from_chunk() fonctionne avec de vrais TagKey."""
        # Créer des TagKeys mock
        tag_key1 = Mock(spec=TagKey)
        tag_key2 = Mock(spec=TagKey)

        chunk = Chunk(index=0, token_encoding="cl100k_base")
        chunk.body = {tag_key1: "text1", tag_key2: "text2"}

        mock_chapter = Mock(spec=ChapterChunk)
        part = ChapterPartChunk.from_chunk(chunk, mock_chapter, total_parts=1)

        # Vérifier que les TagKeys sont présents
        assert tag_key1 in part.body
        assert tag_key2 in part.body
        assert part.body[tag_key1] == "text1"
        assert part.body[tag_key2] == "text2"

    def test_is_first(self):
        """Vérifie que is_first() retourne True pour le premier chunk."""
        chunk = Chunk(index=0, token_encoding="cl100k_base")
        mock_chapter = Mock(spec=ChapterChunk)

        part = ChapterPartChunk.from_chunk(chunk, mock_chapter, total_parts=3)
        assert part.is_first() is True

        # Index non-zero
        chunk2 = Chunk(index=1, token_encoding="cl100k_base")
        part2 = ChapterPartChunk.from_chunk(chunk2, mock_chapter, total_parts=3)
        assert part2.is_first() is False

    def test_is_last(self):
        """Vérifie que is_last() retourne True pour le dernier chunk."""
        mock_chapter = Mock(spec=ChapterChunk)

        # Dernier chunk (index=2, total=3)
        chunk_last = Chunk(index=2, token_encoding="cl100k_base")
        part_last = ChapterPartChunk.from_chunk(chunk_last, mock_chapter, total_parts=3)
        assert part_last.is_last() is True

        # Pas le dernier
        chunk_middle = Chunk(index=1, token_encoding="cl100k_base")
        part_middle = ChapterPartChunk.from_chunk(
            chunk_middle, mock_chapter, total_parts=3
        )
        assert part_middle.is_last() is False

    def test_from_chunk_return_type(self):
        """Vérifie que from_chunk() retourne bien un ChapterPartChunk."""
        chunk = Chunk(index=0, token_encoding="cl100k_base")
        mock_chapter = Mock(spec=ChapterChunk)

        part = ChapterPartChunk.from_chunk(chunk, mock_chapter, total_parts=1)

        assert isinstance(part, ChapterPartChunk)
        assert isinstance(part, Chunk)  # ChapterPartChunk hérite de Chunk
