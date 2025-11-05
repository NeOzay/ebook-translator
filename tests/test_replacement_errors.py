"""
Tests pour la gestion d'erreurs dans replacement.py

Ces tests vérifient que FragmentMismatchError est correctement levée
quand le nombre de segments ne correspond pas au nombre de fragments.
"""

import pytest
from bs4 import BeautifulSoup
from bs4.element import NavigableString

from ebook_translator.htmlpage.replacement import TextReplacer
from ebook_translator.htmlpage.exceptions import FragmentMismatchError
from ebook_translator.htmlpage.bilingual import BilingualFormat


@pytest.fixture
def replacer():
    """Fixture pour créer un TextReplacer."""
    html = "<html><body><p>Test</p></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    return TextReplacer(soup)


def test_fragment_mismatch_error_raised(replacer):
    """Test que FragmentMismatchError est levée si mismatch."""
    # Créer 3 fragments
    html = "<p>Hello <b>world</b> today</p>"
    soup = BeautifulSoup(html, "html.parser")
    p_tag = soup.find("p")

    fragments = [
        child for child in p_tag.descendants
        if isinstance(child, NavigableString) and child.strip()
    ]

    assert len(fragments) == 3  # "Hello ", "world", " today"

    # Traduction avec seulement 2 segments (mismatch)
    translated_text = "Bonjour</>monde"  # Manque 1 segment

    replacer_local = TextReplacer(soup)

    with pytest.raises(FragmentMismatchError) as exc_info:
        replacer_local.replace_multiple_fragments(
            fragments=fragments,
            translated_text=translated_text,
            bilingual_format=BilingualFormat.DISABLE,
            original_text="Hello world today",
        )

    # Vérifier les attributs de l'exception
    error = exc_info.value
    assert error.expected_count == 3
    assert error.actual_count == 2
    assert error.original_text == "Hello world today"
    assert len(error.original_fragments) == 3
    assert len(error.translated_segments) == 2


def test_fragment_mismatch_error_attributes(replacer):
    """Test que les attributs de FragmentMismatchError sont corrects."""
    html = "<p>A <em>B</em> C</p>"
    soup = BeautifulSoup(html, "html.parser")
    p_tag = soup.find("p")

    fragments = [
        child for child in p_tag.descendants
        if isinstance(child, NavigableString) and child.strip()
    ]

    # Traduction avec trop de segments
    translated_text = "1</>2</>3</>4"  # 4 segments au lieu de 3

    replacer_local = TextReplacer(soup)

    with pytest.raises(FragmentMismatchError) as exc_info:
        replacer_local.replace_multiple_fragments(
            fragments=fragments,
            translated_text=translated_text,
            bilingual_format=BilingualFormat.DISABLE,
            original_text="A B C",
        )

    error = exc_info.value

    # Vérifier les fragments originaux
    assert "A" in error.original_fragments
    assert "B" in error.original_fragments
    assert "C" in error.original_fragments

    # Vérifier les segments traduits
    assert "1" in error.translated_segments
    assert "2" in error.translated_segments
    assert "3" in error.translated_segments
    assert "4" in error.translated_segments

    # Vérifier le texte complet
    assert error.original_text == "A B C"

    # Vérifier les comptes
    assert error.expected_count == 3
    assert error.actual_count == 4


def test_valid_replacement_no_error(replacer):
    """Test qu'aucune erreur n'est levée si le nombre de segments est correct."""
    html = "<p>Hello <b>world</b></p>"
    soup = BeautifulSoup(html, "html.parser")
    p_tag = soup.find("p")

    fragments = [
        child for child in p_tag.descendants
        if isinstance(child, NavigableString) and child.strip()
    ]

    assert len(fragments) == 2  # "Hello " et "world"

    # Traduction avec le bon nombre de segments
    translated_text = "Bonjour</>monde"

    replacer_local = TextReplacer(soup)

    # Ne devrait pas lever d'exception
    replacer_local.replace_multiple_fragments(
        fragments=fragments,
        translated_text=translated_text,
        bilingual_format=BilingualFormat.DISABLE,
        original_text="Hello world",
    )

    # Vérifier que le remplacement a réussi
    assert "Bonjour" in p_tag.get_text()
    assert "monde" in p_tag.get_text()


def test_fragment_mismatch_error_message():
    """Test que le message d'erreur de FragmentMismatchError est descriptif."""
    error = FragmentMismatchError(
        original_fragments=["A", "B", "C"],
        translated_segments=["1", "2"],
        original_text="A B C",
        expected_count=3,
        actual_count=2,
    )

    error_msg = str(error)

    # Vérifier que le message contient les infos essentielles
    assert "expected 3" in error_msg.lower()
    assert "got 2" in error_msg.lower()
    assert "mismatch" in error_msg.lower()


def test_fragment_mismatch_error_repr():
    """Test que __repr__ de FragmentMismatchError est informatif."""
    error = FragmentMismatchError(
        original_fragments=["A", "B"],
        translated_segments=["1"],
        original_text="A B",
        expected_count=2,
        actual_count=1,
    )

    repr_str = repr(error)

    # Vérifier que repr contient les comptes
    assert "expected=2" in repr_str
    assert "actual=1" in repr_str
    assert "FragmentMismatchError" in repr_str
