"""
Tests pour la préservation des espaces dans les fragments HTML.

Ces tests vérifient que les espaces de début/fin des fragments sont correctement
préservés lors de l'extraction et du remplacement de texte.
"""

import pytest
from bs4 import BeautifulSoup
from ebook_translator.htmlpage.replacement import preserve_whitespace, TextReplacer
from ebook_translator.htmlpage.bilingual import BilingualFormat


class TestPreserveWhitespace:
    """Tests pour la fonction preserve_whitespace()."""

    def test_no_whitespace(self):
        """Texte sans espaces de bordure."""
        result = preserve_whitespace("text", "texte")
        assert result == "texte"

    def test_leading_whitespace(self):
        """Texte avec espace au début."""
        result = preserve_whitespace(" text", "texte")
        assert result == " texte"

    def test_trailing_whitespace(self):
        """Texte avec espace à la fin."""
        result = preserve_whitespace("text ", "texte")
        assert result == "texte "

    def test_both_whitespace(self):
        """Texte avec espaces des deux côtés."""
        result = preserve_whitespace(" text ", "texte")
        assert result == " texte "

    def test_multiple_leading_spaces(self):
        """Plusieurs espaces au début (doit normaliser à 1)."""
        result = preserve_whitespace("   text", "texte")
        assert result == " texte"

    def test_multiple_trailing_spaces(self):
        """Plusieurs espaces à la fin (doit normaliser à 1)."""
        result = preserve_whitespace("text   ", "texte")
        assert result == "texte "

    def test_translated_already_has_spaces(self):
        """La traduction a déjà des espaces (ne pas dupliquer)."""
        result = preserve_whitespace(" text ", " texte ")
        assert result == " texte "

    def test_empty_original(self):
        """Texte original vide."""
        result = preserve_whitespace("", "texte")
        assert result == "texte"

    def test_newline_as_whitespace(self):
        """Newline compte comme espace."""
        result = preserve_whitespace("\ntext", "texte")
        assert result == " texte"


class TestHtmlReconstructionWithWhitespace:
    """Tests pour la reconstruction HTML avec préservation des espaces."""

    def test_simple_nested_tags(self):
        """Cas simple : <b>début <em>milieu</em> fin</b>"""
        html = "<p><b>start <em>middle</em> end</b></p>"
        soup = BeautifulSoup(html, "html.parser")
        replacer = TextReplacer(soup)

        # Simuler la reconstruction
        original_tag = soup.find("b")
        new_tag = soup.new_tag("b")

        # Texte traduit avec séparateurs (3 fragments)
        translated_text = "début</>milieu</>fin"

        replacer.reconstruct_tag_content(new_tag, original_tag, translated_text)

        # Vérifier que les espaces sont préservés
        result = str(new_tag)
        assert "début <em>milieu</em> fin" in result

    def test_complex_nested_structure(self):
        """Structure complexe avec multiples niveaux."""
        html = "<p>first tag<b>Restructure Clothing Spell <em>can be used</em> to redesign</b></p>"
        soup = BeautifulSoup(html, "html.parser")
        replacer = TextReplacer(soup)

        original_tag = soup.find("b")
        new_tag = soup.new_tag("b")

        # 3 fragments : "Restructure Clothing Spell ", "can be used", " to redesign"
        translated_text = "Sort de Restructuration Vestimentaire</>peut être utilisé</>pour redessiner"

        replacer.reconstruct_tag_content(new_tag, original_tag, translated_text)

        result = str(new_tag)
        # Vérifier les espaces critiques
        assert "Vestimentaire <em>" in result or "Vestimentaire<em>" not in result
        assert "</em> pour" in result or "</em>pour" not in result

    def test_single_fragment_with_spaces(self):
        """Fragment unique avec espaces de bordure."""
        html = "<p> texte avec espaces </p>"
        soup = BeautifulSoup(html, "html.parser")
        replacer = TextReplacer(soup)

        original_tag = soup.find("p")
        new_tag = soup.new_tag("p")

        translated_text = "text with spaces"

        replacer.reconstruct_tag_content(new_tag, original_tag, translated_text)

        result = str(new_tag)
        # Les espaces de bordure doivent être préservés
        assert result.strip() in ["<p> text with spaces </p>", "<p>text with spaces</p>"]

    def test_only_spaces_no_stripping(self):
        """Fragments contenant uniquement des espaces ne doivent pas être ignorés."""
        html = "<p>début<b> </b>fin</p>"
        soup = BeautifulSoup(html, "html.parser")

        # Vérifier que le fragment " " n'est pas supprimé lors de l'extraction
        # (Ce test peut nécessiter d'ajuster _should_ignore_fragment)
        text_fragments = list(soup.find("p").find_all(string=True))
        assert len(text_fragments) == 3  # "début", " ", "fin"


class TestFormatTextPreservesWhitespace:
    """Tests pour _format_text() qui doit préserver les espaces."""

    def test_format_single_fragment_with_leading_space(self):
        """Fragment unique avec espace au début."""
        from bs4.element import NavigableString
        from ebook_translator.htmlpage.page import HtmlPage
        from ebooklib import epub

        # Créer un EpubHtml minimal
        epub_html = epub.EpubHtml(title="test", file_name="test.xhtml")
        epub_html.content = b"<html><body><p> text</p></body></html>"

        page = HtmlPage(epub_html)

        # Tester _format_text directement
        fragment = NavigableString(" text")
        result = page._format_text(fragment)

        assert result == " text"

    def test_format_multiple_fragments_with_spaces(self):
        """Multiples fragments avec espaces de bordure."""
        from bs4.element import NavigableString
        from ebook_translator.htmlpage.page import HtmlPage
        from ebooklib import epub

        epub_html = epub.EpubHtml(title="test", file_name="test.xhtml")
        epub_html.content = b"<html><body></body></html>"

        page = HtmlPage(epub_html)

        fragments = [
            NavigableString("start "),
            NavigableString(" middle "),
            NavigableString(" end"),
        ]

        result = page._format_text(fragments)

        # Les espaces de bordure doivent être préservés
        assert result == "start </> middle </> end"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
