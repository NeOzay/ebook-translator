"""Fixtures pour tests HTML."""

from pathlib import Path

import pytest

from ebook_translator.htmlpage import TagKey


@pytest.fixture
def sample_html(tmp_path: Path) -> Path:
    """Fichier HTML de test."""
    html_file = tmp_path / "test.html"
    html_file.write_text(
        """<!DOCTYPE html>
<html>
<body>
    <p>First paragraph.</p>
    <p>Second</>paragraph.</p>
</body>
</html>"""
    )
    return html_file


@pytest.fixture
def tag_key() -> TagKey:
    """TagKey de base pour tests."""
    return TagKey(tag_name="p", index=0)
