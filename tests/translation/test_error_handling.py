"""
Tests pour la gestion d'erreurs et le système de retry.
"""

import pytest


class TestFragmentMismatchErrorMessage:
    """Tests pour les messages d'erreur de mismatch de fragments."""

    def test_error_message_format(self):
        """Test : Vérifier que FragmentMismatchError est levée avec les bonnes données."""
        from bs4 import BeautifulSoup
        from bs4.element import NavigableString
        from src.ebook_translator.htmlpage import BilingualFormat
        from src.ebook_translator.htmlpage.exceptions import FragmentMismatchError
        from src.ebook_translator.htmlpage.replacement import TextReplacer

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
                original_text="Hello World",  # Passer le texte original
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
        assert "mismatch" in error_msg.lower() or "Mismatch" in error_msg
        assert "2" in error_msg  # expected count
        assert "1" in error_msg  # actual count


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
