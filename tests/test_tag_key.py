"""
Tests unitaires pour le module TagKey.

Ces tests vérifient le comportement des clés de tags HTML
utilisées pour identifier les fragments de texte.
"""

import pytest
from bs4 import BeautifulSoup
from unittest.mock import Mock
from ebook_translator.htmlpage.tag_key import TagKey


class TestTagKey:
    """Tests pour la classe TagKey."""

    def test_index_is_always_string(self):
        """Vérifie que l'index est toujours converti en string."""
        soup = BeautifulSoup("<p>Test</p>", "html.parser")
        tag = soup.find("p")
        page = Mock()

        # Passer un int
        key = TagKey(index=42, tag=tag, page=page)

        # Vérifier que c'est stocké comme string
        assert isinstance(key.index, str)
        assert key.index == "42"

    def test_tag_key_equality_by_identity(self):
        """Vérifie que deux TagKey sont égaux seulement si même objet Tag."""
        soup = BeautifulSoup("<p>Test</p><p>Test</p>", "html.parser")
        tags = soup.find_all("p")
        page = Mock()

        # Deux tags avec le même contenu mais des objets différents
        key1 = TagKey(index=0, tag=tags[0], page=page)
        key2 = TagKey(index=0, tag=tags[1], page=page)

        # Ne doivent PAS être égaux (différents objets)
        assert key1 != key2

        # Même tag, doit être égal
        key3 = TagKey(index=0, tag=tags[0], page=page)
        assert key1 == key3

    def test_tag_key_hashable(self):
        """Vérifie que TagKey peut être utilisé comme clé de dictionnaire."""
        soup = BeautifulSoup("<p>Test</p>", "html.parser")
        tag = soup.find("p")
        page = Mock()

        key = TagKey(index=0, tag=tag, page=page)

        # Doit pouvoir être utilisé comme clé
        test_dict = {key: "valeur"}
        assert test_dict[key] == "valeur"

    def test_tag_key_hash_stability(self):
        """Vérifie que le hash d'un TagKey reste constant."""
        soup = BeautifulSoup("<p>Test</p>", "html.parser")
        tag = soup.find("p")
        page = Mock()

        key = TagKey(index=0, tag=tag, page=page)

        # Le hash doit rester le même
        hash1 = hash(key)
        hash2 = hash(key)
        assert hash1 == hash2

    def test_tag_key_repr(self):
        """Vérifie la représentation string pour le debug."""
        soup = BeautifulSoup("<p>Test</p>", "html.parser")
        tag = soup.find("p")
        page = Mock()
        page.epub_html.file_name = "test.html"

        key = TagKey(index=5, tag=tag, page=page)

        repr_str = repr(key)
        assert "TagKey" in repr_str
        assert "index=5" in repr_str
        assert "tag=p" in repr_str
        assert "test.html" in repr_str

    def test_different_indices_same_tag(self):
        """Vérifie que différents indices avec même tag sont égaux (identité du tag)."""
        soup = BeautifulSoup("<p>Test</p>", "html.parser")
        tag = soup.find("p")
        page = Mock()

        # Même tag, indices différents
        key1 = TagKey(index=0, tag=tag, page=page)
        key2 = TagKey(index=999, tag=tag, page=page)

        # Doivent être égaux car même objet tag (identité)
        assert key1 == key2
        # Mais les index sont différents
        assert key1.index != key2.index

    def test_tag_key_stores_page_reference(self):
        """Vérifie que TagKey conserve la référence à la page."""
        soup = BeautifulSoup("<p>Test</p>", "html.parser")
        tag = soup.find("p")
        page = Mock()

        key = TagKey(index=0, tag=tag, page=page)

        assert key.page is page
