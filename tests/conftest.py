"""
Configuration pytest pour les tests ebook-translator.

Ce fichier contient les fixtures communes à tous les tests.
"""

import pytest
from pathlib import Path


@pytest.fixture
def tmp_cache_dir(tmp_path):
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
