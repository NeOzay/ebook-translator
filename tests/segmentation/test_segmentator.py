"""
Tests pour la classe Segmentator.

Tests unitaires : repr, initialisation.
Tests d'intégration : utilise le vrai EPUB (Le Petit Prince) via fixtures
  de conftest.py pour vérifier get_all_segments() et get_all_chapters_by_spine().
"""

from typing import cast
from unittest.mock import Mock

from ebooklib import epub

from ebook_translator.segmentation import Chunk, Segmentator
from ebook_translator.segmentation.chapter_chunk import ChapterChunk


class TestSegmentatorUnit:
    """Tests unitaires de Segmentator (sans EPUB réel)."""

    def test_repr_standard_overlap(self):
        """repr affiche pages, max_tokens et overlap en pourcentage."""
        mock_htmls = cast(
            list[epub.EpubHtml], [Mock(spec=epub.EpubHtml) for _ in range(3)]
        )
        seg = Segmentator(epub_source=mock_htmls, max_tokens=2000, overlap_ratio=0.2)

        repr_str = repr(seg)

        assert "Segmentator" in repr_str
        assert "pages=3" in repr_str
        assert "max_tokens=2000" in repr_str
        assert "overlap=20%" in repr_str

    def test_repr_extended_overlap(self):
        """repr affiche l'overlap en multiple de max_tokens quand ratio >= 1.0."""
        seg = Segmentator(epub_source=[], max_tokens=1000, overlap_ratio=2.0)

        repr_str = repr(seg)

        assert "2.0×" in repr_str

    def test_init_stores_params(self):
        """L'initialisation stocke correctement les paramètres."""
        mock_htmls = cast(
            list[epub.EpubHtml], [Mock(spec=epub.EpubHtml) for _ in range(2)]
        )
        seg = Segmentator(
            epub_source=mock_htmls,
            max_tokens=500,
            overlap_ratio=0.1,
            encoding="cl100k_base",
        )

        assert seg.max_tokens == 500
        assert seg.overlap_ratio == 0.1
        assert seg.encoding == "cl100k_base"
        assert len(seg.epub_htmls) == 2


class TestSegmentatorIntegration:
    """Tests d'intégration avec le vrai EPUB (Le Petit Prince)."""

    def test_get_all_segments_returns_chunks(self, all_chunks: list[Chunk]):
        """get_all_segments() yield des instances Chunk."""
        assert len(all_chunks) > 0
        for chunk in all_chunks:
            assert isinstance(chunk, Chunk)

    def test_chunk_indices_are_sequential(self, all_chunks: list[Chunk]):
        """Les indices des chunks sont séquentiels (0, 1, 2, ...)."""
        for expected_index, chunk in enumerate(all_chunks):
            assert chunk.index == expected_index

    def test_first_chunk_has_no_head(self, all_chunks: list[Chunk]):
        """Le premier chunk n'a pas de head (aucun contexte précédent)."""
        first = all_chunks[0]
        assert first.get_head_size() == 0

    def test_non_first_chunks_have_head(self, all_chunks: list[Chunk]):
        """Les chunks suivants ont un head non vide (contexte overlap)."""
        # Le 2e chunk doit avoir du contexte depuis le 1er
        assert len(all_chunks) >= 2
        second = all_chunks[1]
        assert second.get_head_size() > 0

    def test_all_chunks_body_not_empty(self, all_chunks: list[Chunk]):
        """Chaque chunk a au moins un fragment dans son body."""
        for chunk in all_chunks:
            assert chunk.get_body_size() > 0, f"Chunk {chunk.index} a un body vide"

    def test_chunk_str_contains_llm_markers(self, all_chunks: list[Chunk]):
        """str(chunk) contient les balises <N/> attendues par le LLM."""
        for chunk in all_chunks:
            result = str(chunk)
            assert "<0/>" in result, f"Chunk {chunk.index} manque la balise <0/>"

    def test_get_all_chapters_by_spine_returns_chapter_chunks(
        self, all_chapters: list[ChapterChunk]
    ):
        """get_all_chapters_by_spine() yield des ChapterChunk avec contenu."""
        assert len(all_chapters) > 0
        for chapter in all_chapters:
            assert isinstance(chapter, ChapterChunk)
            assert chapter.get_body_size() > 0

    def test_chapters_have_names(self, all_chapters: list[ChapterChunk]):
        """Chaque chapitre détecté a un nom non vide."""
        for chapter in all_chapters:
            assert isinstance(chapter.name, str)
            assert len(chapter.name) > 0

    def test_chapters_have_files(self, all_chapters: list[ChapterChunk]):
        """Chaque chapitre référence au moins un fichier HTML."""
        for chapter in all_chapters:
            assert len(chapter.files) >= 1
            assert len(chapter.files_names) >= 1

    def test_chapters_indices_monotonic(self, all_chapters: list[ChapterChunk]):
        """Les index de chapitres sont strictement croissants.

        Non contigus : les chapitres image-only sont filtrés mais incrémentent
        quand même l'index du détecteur.
        """
        for i in range(1, len(all_chapters)):
            assert all_chapters[i].index > all_chapters[i - 1].index

    def test_stop_chunk_end_of_chapter_mode(self, chapter_segmentator: Segmentator):
        """Mode stop_chunk_end_of_chapter yield des chunks par chapitre."""
        chunks = list(
            chapter_segmentator.get_all_segments(
                segmentation_logic="stop_chunk_end_of_chapter"
            )
        )
        assert len(chunks) > 0
        for chunk in chunks:
            assert isinstance(chunk, Chunk)
            assert chunk.get_body_size() > 0
