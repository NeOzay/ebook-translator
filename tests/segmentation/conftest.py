"""Fixtures pour tests de segmentation."""

from unittest.mock import Mock

import pytest

from ebook_translator.segmentation import Chunk


@pytest.fixture
def sample_chunk() -> Chunk:
    """Chunk de base avec 5 lignes pour tests."""
    chunk = Chunk(index=0)
    # body est un dict avec des tag_keys mockés comme clés
    chunk.body = {Mock(name=f"tag_{i}"): f"Line {i}" for i in range(5)}
    return chunk
