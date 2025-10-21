"""
Tests pour la gestion d'erreurs et le système de retry.
"""

import pytest
from src.ebook_translator.translation.parser import parse_llm_translation_output


class TestParserErrorHandling:
    """Tests pour les messages d'erreur du parser."""

    def test_parse_missing_end_marker(self):
        """Test : Erreur si le marqueur [=[END]=] est manquant."""
        output = "<0/>Hello\n<1/>World"

        with pytest.raises(ValueError) as exc_info:
            parse_llm_translation_output(output)

        error_msg = str(exc_info.value)
        assert "marqueur [=[END]=] est manquant" in error_msg
        assert "💡 Causes possibles" in error_msg
        assert "🔧 Solutions" in error_msg

    def test_parse_llm_error_response(self):
        """Test : Détection des messages d'erreur du LLM."""
        output = "[ERREUR: Timeout - Le serveur n'a pas répondu à temps]"

        with pytest.raises(ValueError) as exc_info:
            parse_llm_translation_output(output)

        error_msg = str(exc_info.value)
        assert "Le LLM a retourné une erreur" in error_msg
        assert "Timeout" in error_msg

    def test_parse_no_segments_found(self):
        """Test : Erreur si aucun segment n'est trouvé."""
        output = "Some random text without proper format\n[=[END]=]"

        with pytest.raises(ValueError) as exc_info:
            parse_llm_translation_output(output)

        error_msg = str(exc_info.value)
        assert "Aucun segment trouvé" in error_msg
        assert "Format attendu" in error_msg
        assert "<0/>Texte traduit" in error_msg

    def test_parse_valid_output(self):
        """Test : Parsing réussi avec un format valide."""
        output = "<0/>Bonjour\n<1/>Monde\n<2/>Test\n[=[END]=]"

        result = parse_llm_translation_output(output)

        assert result == {
            0: "Bonjour",
            1: "Monde",
            2: "Test"
        }

    def test_parse_with_fragment_separators(self):
        """Test : Parsing avec séparateurs de fragments.</>.
        """
        output = "<0/>Hello</>World\n<1/>Foo</>Bar</>Baz\n[=[END]=]"

        result = parse_llm_translation_output(output)

        assert result == {
            0: "Hello</>World",
            1: "Foo</>Bar</>Baz"
        }

    def test_parse_multiline_text(self):
        """Test : Parsing avec texte multilignes."""
        output = """<0/>First line
Second line
Third line
<1/>Another paragraph
with multiple lines
[=[END]=]"""

        result = parse_llm_translation_output(output)

        assert 0 in result
        assert 1 in result
        # Le texte est capturé avec .strip(), donc les lignes sont condensées
        assert "First line" in result[0]
        assert "Another paragraph" in result[1]


class TestFragmentMismatchErrorMessage:
    """Tests pour les messages d'erreur de mismatch de fragments."""

    def test_error_message_format(self):
        """Test : Vérifier que FragmentMismatchError est levée avec les bonnes données."""
        from bs4 import BeautifulSoup, NavigableString
        from src.ebook_translator.htmlpage.replacement import TextReplacer
        from src.ebook_translator.htmlpage import BilingualFormat
        from src.ebook_translator.htmlpage.exceptions import FragmentMismatchError

        # Créer un faux fragment
        soup = BeautifulSoup("<p>Hello World</p>", "html.parser")
        p_tag = soup.find("p")
        assert p_tag is not None

        # Créer des fragments
        fragments = [NavigableString("Hello"), NavigableString("World")]
        for frag in fragments:
            p_tag.append(frag)

        # Traduction avec mauvais nombre de segments
        translated_text = "Bonjour"  # 1 segment au lieu de 2

        replacer = TextReplacer(soup)

        with pytest.raises(FragmentMismatchError) as exc_info:
            replacer.replace_multiple_fragments(
                fragments,
                translated_text,
                BilingualFormat.DISABLE,
                original_text="Hello World"  # Passer le texte original
            )

        error = exc_info.value

        # Vérifier que l'exception contient les bonnes données
        assert error.expected_count == 2
        assert error.actual_count == 1
        assert len(error.original_fragments) == 2
        assert "Hello" in error.original_fragments
        assert "World" in error.original_fragments
        assert len(error.translated_segments) == 1
        assert "Bonjour" in error.translated_segments
        assert error.original_text == "Hello World"

        # Vérifier le message d'erreur basique
        error_msg = str(error)
        assert ("mismatch" in error_msg.lower() or "Mismatch" in error_msg)
        assert "2" in error_msg  # expected count
        assert "1" in error_msg  # actual count


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
