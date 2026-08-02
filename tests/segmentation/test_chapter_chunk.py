"""
Tests unitaires pour le module ChapterChunk.

Ces tests vérifient le comportement des classes ChapterChunk et ChapterPartChunk,
notamment la conversion type-safe via from_chunk().
"""

from unittest.mock import Mock

import pytest

from ebook_translator.htmlpage.tag_key import TagKey
from ebook_translator.segmentation import Chunk
from ebook_translator.segmentation.chapter_chunk import ChapterChunk, ChapterPartChunk
from tests.conftest import make_TagKey_mock


def make_chapter_mock(index: int = 0) -> ChapterChunk:
    """Mock de ChapterChunk portant un index réel.

    `index` est un champ de dataclass sans valeur par défaut : il n'existe pas
    sur la classe, donc `Mock(spec=ChapterChunk)` ne le fournit pas. Or
    `from_chunk` le lit pour calculer l'index global.

    Args:
        index: Index du chapitre parent

    Returns:
        Mock de ChapterChunk avec l'index spécifié
    """
    mock_chapter = Mock(spec=ChapterChunk)
    mock_chapter.index = index
    return mock_chapter


class TestChapterPartChunk:
    """Tests pour la classe ChapterPartChunk."""

    def test_from_chunk_copies_all_attributes(self):
        """Vérifie que from_chunk() copie tous les attributs de Chunk."""
        head_key = make_TagKey_mock(0)
        body_key = make_TagKey_mock(1)
        tail_key = make_TagKey_mock(2)

        chunk = Chunk(index=5, token_count=100, token_encoding="cl100k_base")
        chunk.head = {head_key: "head_text"}
        chunk.body = {body_key: "body_text"}
        chunk.tail = {tail_key: "tail_text"}

        mock_chapter = make_chapter_mock(index=2)

        part = ChapterPartChunk.from_chunk(chunk, mock_chapter, total_parts=3)

        # Index global : chapitre 2, partie 5 => 205
        assert part.index == 205
        assert part.part == 5
        assert part.token_count == 100
        assert part.token_encoding == "cl100k_base"
        assert part.total_parts == 3
        assert part.chapter is mock_chapter

    def test_from_chunk_rejects_part_index_over_99(self):
        """Un index de partie >= 100 casserait l'encodage global, donc lève."""
        chunk = Chunk(index=100, token_encoding="cl100k_base")
        mock_chapter = make_chapter_mock(index=1)

        with pytest.raises(ValueError, match="less than 100"):
            _ = ChapterPartChunk.from_chunk(chunk, mock_chapter, total_parts=101)

    def test_from_chunk_copies_dictionaries_independently(self):
        """Vérifie que les dictionnaires sont copiés indépendamment (pas de références partagées)."""
        key1 = make_TagKey_mock(0)
        key2 = make_TagKey_mock(1)
        key3 = make_TagKey_mock(2)

        chunk = Chunk(index=0, token_encoding="cl100k_base")
        chunk.head = {key1: "value1"}
        chunk.body = {key2: "value2"}
        chunk.tail = {key3: "value3"}

        mock_chapter = make_chapter_mock()

        part = ChapterPartChunk.from_chunk(chunk, mock_chapter, total_parts=1)

        # Ajouter une nouvelle clé dans le chunk original
        new_key = make_TagKey_mock(99)
        chunk.head[new_key] = "new_head"
        chunk.body[new_key] = "new_body"
        chunk.tail[new_key] = "new_tail"

        # Vérifier que part n'est PAS affecté
        assert new_key not in part.head
        assert new_key not in part.body
        assert new_key not in part.tail

        # Vérifier que les valeurs originales sont présentes
        assert part.head[key1] == "value1"
        assert part.body[key2] == "value2"
        assert part.tail[key3] == "value3"

    def test_from_chunk_with_empty_dictionaries(self):
        """Vérifie que from_chunk() fonctionne avec des dictionnaires vides."""
        chunk = Chunk(index=0, token_count=0, token_encoding="cl100k_base")
        # head, body, tail sont vides par défaut

        mock_chapter = make_chapter_mock()
        part = ChapterPartChunk.from_chunk(chunk, mock_chapter, total_parts=1)

        assert len(part.head) == 0
        assert len(part.body) == 0
        assert len(part.tail) == 0

    def test_from_chunk_with_tagkey_dictionaries(self):
        """Vérifie que from_chunk() fonctionne avec de vrais TagKey."""
        tag_key1 = Mock(spec=TagKey)
        tag_key2 = Mock(spec=TagKey)

        chunk = Chunk(index=0, token_encoding="cl100k_base")
        chunk.body = {tag_key1: "text1", tag_key2: "text2"}  # type: ignore[reportArgumentType]

        mock_chapter = make_chapter_mock()
        part = ChapterPartChunk.from_chunk(chunk, mock_chapter, total_parts=1)

        assert tag_key1 in part.body
        assert tag_key2 in part.body
        assert part.body[tag_key1] == "text1"  # type: ignore[index]
        assert part.body[tag_key2] == "text2"  # type: ignore[index]

    def test_is_first(self):
        """Vérifie que is_first() retourne True pour le premier chunk."""
        chunk = Chunk(index=0, token_encoding="cl100k_base")
        mock_chapter = make_chapter_mock()

        part = ChapterPartChunk.from_chunk(chunk, mock_chapter, total_parts=3)
        assert part.is_first() is True

        chunk2 = Chunk(index=1, token_encoding="cl100k_base")
        part2 = ChapterPartChunk.from_chunk(chunk2, mock_chapter, total_parts=3)
        assert part2.is_first() is False

    def test_is_last(self):
        """Vérifie que is_last() retourne True pour le dernier chunk."""
        mock_chapter = make_chapter_mock()

        chunk_last = Chunk(index=2, token_encoding="cl100k_base")
        part_last = ChapterPartChunk.from_chunk(chunk_last, mock_chapter, total_parts=3)
        assert part_last.is_last() is True

        chunk_middle = Chunk(index=1, token_encoding="cl100k_base")
        part_middle = ChapterPartChunk.from_chunk(
            chunk_middle, mock_chapter, total_parts=3
        )
        assert part_middle.is_last() is False

    def test_from_chunk_return_type(self):
        """Vérifie que from_chunk() retourne bien un ChapterPartChunk."""
        chunk = Chunk(index=0, token_encoding="cl100k_base")
        mock_chapter = make_chapter_mock()

        part = ChapterPartChunk.from_chunk(chunk, mock_chapter, total_parts=1)

        assert isinstance(part, ChapterPartChunk)
        assert isinstance(part, Chunk)  # ChapterPartChunk hérite de Chunk


class TestChapterChunkIntegration:
    """Tests d'intégration utilisant les vrais chapitres du EPUB."""

    def test_chapter_chunk_has_metadata(self, all_chapters: list[ChapterChunk]):
        """ChapterChunk a les métadonnées name, files, files_names."""
        assert len(all_chapters) > 0
        chapter = all_chapters[0]

        assert isinstance(chapter.name, str)
        assert len(chapter.name) > 0
        assert isinstance(chapter.files, list)
        assert len(chapter.files) >= 1
        assert isinstance(chapter.files_names, list)
        assert len(chapter.files_names) >= 1

    def test_chapter_chunk_has_body(self, all_chapters: list[ChapterChunk]):
        """ChapterChunk a un body non vide (texte extrait du fichier HTML)."""
        for chapter in all_chapters:
            assert chapter.get_body_size() > 0, (
                f"Chapitre '{chapter.name}' a un body vide"
            )

    def test_chapter_chunk_token_count_positive(self, all_chapters: list[ChapterChunk]):
        """ChapterChunk a un token_count positif."""
        for chapter in all_chapters:
            assert chapter.token_count > 0

    def test_chapter_chunk_files_names_match(self, all_chapters: list[ChapterChunk]):
        """files_names correspond aux get_name() des fichiers."""
        for chapter in all_chapters:
            assert len(chapter.files) == len(chapter.files_names)
            for epub_html, name in zip(
                chapter.files, chapter.files_names, strict=False
            ):
                assert epub_html.get_name() == name

    def test_chapter_chunk_split_yields_parts(self, all_chapters: list[ChapterChunk]):
        """split_chunk() yield des ChapterPartChunk."""
        large_chapters = [c for c in all_chapters if c.token_count > 100]
        assert len(large_chapters) > 0, "Aucun chapitre assez long pour tester split"

        chapter = large_chapters[0]
        parts = list(chapter.split_chunk(max_tokens=50, overlap_ratio=0.1))

        assert len(parts) >= 1
        for part in parts:
            assert isinstance(part, ChapterPartChunk)
            assert part.chapter is chapter

    def test_chapter_part_chunk_is_first_last(self, all_chapters: list[ChapterChunk]):
        """is_first() et is_last() corrects selon la position dans le split."""
        large_chapters = [c for c in all_chapters if c.token_count > 100]
        chapter = large_chapters[0]
        parts = list(chapter.split_chunk(max_tokens=50, overlap_ratio=0.1))

        if len(parts) >= 2:
            assert parts[0].is_first() is True
            assert parts[-1].is_last() is True
            assert parts[0].is_last() is False
            assert parts[-1].is_first() is False

    def test_chapter_part_total_parts_consistent(
        self, all_chapters: list[ChapterChunk]
    ):
        """total_parts est cohérent avec le nombre réel de parties."""
        large_chapters = [c for c in all_chapters if c.token_count > 100]
        chapter = large_chapters[0]
        parts = list(chapter.split_chunk(max_tokens=50, overlap_ratio=0.1))

        for part in parts:
            assert part.total_parts == len(parts)
