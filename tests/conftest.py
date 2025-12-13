"""
Configuration pytest pour les tests ebook-translator.

Ce fichier contient les fixtures communes à tous les tests.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest
from bs4 import Tag
from ebooklib import epub

from ebook_translator.checks import ValidationContext
from ebook_translator.htmlpage import TagKey
from ebook_translator.llm.llm import LLM
from ebook_translator.segmentation import Chunk
from ebook_translator.segmentation.segmentator import Segmentator
from ebook_translator.translation.epub_handler import extract_html_items_in_spine_order

source_epub = Path("tests/Saint-Exupery-Le_Petit_Prince.epub")
source_book = epub.read_epub(source_epub)
html_items, target_book = extract_html_items_in_spine_order(source_book)

segmentator = Segmentator(html_items, 150)

a_chunk = segmentator.get_all_segments().__next__()


@pytest.fixture
def tmp_cache_dir(tmp_path: Path) -> Path:
    """
    Fixture fournissant un répertoire temporaire pour les caches.

    Args:
        tmp_path: Fixture pytest fournissant un répertoire temporaire

    Returns:
        Path vers le répertoire de cache temporaire
    """
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir


def make_TagKey_mock(index: int) -> TagKey:
    """
    Crée un mock de TagKey avec un index donné.

    Args:
        index: L'index à assigner au mock

    Returns:
        Mock de TagKey avec l'index spécifié
    """
    tag_key_mock = TagKey(index=index, tag=Mock(spec=Tag), page=Mock())
    tag_key_mock.index = str(index)  # Toujours string pour cohérence avec Store
    return tag_key_mock


@pytest.fixture
def chunk() -> Chunk:
    """
    Fixture fournissant une instance de Chunk.

    Returns:
        Instance de Chunk
    """

    return a_chunk


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


@pytest.fixture
def val_context(mock_chunk: Chunk, mock_llm: LLM):
    """Contexte de validation mock."""
    yield ValidationContext(
        chunk=mock_chunk,
        translated_texts={},
        original_texts={},
        llm=mock_llm,
        target_language="fr",
        max_retries=2,
        chunk_info=Mock(),
    )
