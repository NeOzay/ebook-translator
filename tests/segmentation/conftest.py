"""Fixtures pour tests de segmentation."""

import itertools

import pytest

import tests.conftest as root_conftest
from ebook_translator.segmentation import Chunk
from ebook_translator.segmentation.chapter_chunk import ChapterChunk
from ebook_translator.segmentation.segmentator import Segmentator


@pytest.fixture(scope="session")
def chapter_segmentator() -> Segmentator:
    """Segmentator configuré pour l'analyse par chapitres (tokens larges)."""
    return Segmentator(root_conftest.source_book, 8000)


@pytest.fixture(scope="session")
def all_chunks() -> list[Chunk]:
    """Liste des 20 premiers chunks du vrai EPUB (max_tokens=150)."""
    seg = Segmentator(root_conftest.html_items, 150)
    return list(itertools.islice(seg.get_all_segments(), 20))


@pytest.fixture(scope="session")
def all_chapters(chapter_segmentator: Segmentator) -> list[ChapterChunk]:
    """Liste de tous les chapitres détectés dans le vrai EPUB."""
    return list(chapter_segmentator.get_all_chapters_by_spine())
