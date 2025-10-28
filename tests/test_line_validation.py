"""
Tests pour la validation du nombre de lignes dans les traductions.
"""

import pytest
from ebook_translator.checks.line_count_check import count_expected_lines
from ebook_translator.translation.parser import parse_llm_translation_output


# validate_line_count a été supprimée, logique déplacée dans LineCountCheck
def validate_line_count(
    translations: dict[int, str],
    expected_count: int | None = None,
    source_content: str | None = None
) -> tuple[bool, str | None]:
    """Fonction de compatibilité pour tests existants."""
    if expected_count is None and source_content is None:
        raise ValueError("Au moins un de expected_count ou source_content doit être fourni")

    if expected_count is None and source_content is not None:
        expected_count = count_expected_lines(source_content)

    actual = len(translations)
    expected_indices = set(range(expected_count))  # type: ignore
    actual_indices = set(translations.keys())

    if expected_count == actual:
        return True, None

    # Construire message d'erreur détaillé
    missing = sorted(expected_indices - actual_indices)
    extra = sorted(actual_indices - expected_indices)

    error_parts = [f"Attendu: {expected_count} lignes", f"Reçu: {actual} lignes"]

    if missing:
        missing_str = ", ".join(f"<{i}/>" for i in missing[:10])
        if len(missing) > 10:
            missing_str += f" (+{len(missing) - 10} autres)"
        error_parts.append(f"Lignes manquantes: {missing_str}")

    if extra:
        extra_str = ", ".join(f"<{i}/>" for i in extra[:10])
        if len(extra) > 10:
            extra_str += f" (+{len(extra) - 10} autres)"
        error_parts.append(f"Lignes en trop: {extra_str}")

    return False, "\n".join(error_parts)


class TestCountExpectedLines:
    """Tests pour count_expected_lines()."""

    def test_simple_content(self):
        """Test avec contenu simple."""
        content = "<0/>Hello\n<1/>World\n<2/>!"
        assert count_expected_lines(content) == 3

    def test_with_context_lines(self):
        """Test avec lignes de contexte (sans <N/>)."""
        content = """<0/>First line
Context line without tag
<1/>Second line
More context
<2/>Third line"""
        assert count_expected_lines(content) == 3

    def test_non_sequential_indices(self):
        """Test avec indices non séquentiels."""
        content = "<5/>Line 5\n<10/>Line 10\n<25/>Line 25"
        assert count_expected_lines(content) == 3

    def test_empty_content(self):
        """Test avec contenu vide."""
        assert count_expected_lines("") == 0

    def test_multiline_text(self):
        """Test avec texte multiligne après balise."""
        content = """<0/>First line
with continuation
<1/>Second line
also multiline
<2/>Third"""
        assert count_expected_lines(content) == 3


class TestValidateLineCount:
    """Tests pour validate_line_count()."""

    def test_valid_translation(self):
        """Test avec traduction valide (compte correct)."""
        translations = {0: "Hello", 1: "World", 2: "!"}
        is_valid, error = validate_line_count(translations, expected_count=3)
        assert is_valid is True
        assert error is None

    def test_missing_lines(self):
        """Test avec lignes manquantes."""
        translations = {0: "Hello", 2: "!"}  # Manque ligne 1
        is_valid, error = validate_line_count(translations, expected_count=3)
        assert is_valid is False
        assert error is not None
        assert "Attendu: 3 lignes" in error
        assert "Reçu: 2 lignes" in error
        assert "<1/>" in error

    def test_extra_lines(self):
        """Test avec lignes en trop."""
        translations = {0: "Hello", 1: "World", 2: "!", 3: "Extra"}
        is_valid, error = validate_line_count(translations, expected_count=3)
        assert is_valid is False
        assert error is not None
        assert "Attendu: 3 lignes" in error
        assert "Reçu: 4 lignes" in error
        assert "<3/>" in error

    def test_with_source_content(self):
        """Test en calculant expected_count depuis source_content."""
        translations = {0: "Bonjour", 1: "Monde"}
        source = "<0/>Hello\n<1/>World"
        is_valid, error = validate_line_count(
            translations, source_content=source
        )
        assert is_valid is True
        assert error is None

    def test_many_missing_lines(self):
        """Test avec beaucoup de lignes manquantes (vérifier troncature)."""
        # Seulement 5 lignes sur 20
        translations = {i: f"Line {i}" for i in [0, 5, 10, 15, 19]}
        is_valid, error = validate_line_count(translations, expected_count=20)
        assert is_valid is False
        assert error is not None
        assert "15 lignes" in error or "manquantes" in error

    def test_no_params_raises_error(self):
        """Test qu'une erreur est levée si ni expected_count ni source_content."""
        translations = {0: "Hello"}
        with pytest.raises(ValueError, match="Au moins un de"):
            validate_line_count(translations)


class TestIntegrationWithParser:
    """Tests d'intégration avec parse_llm_translation_output."""

    def test_complete_output(self):
        """Test avec sortie LLM complète."""
        output = """<0/>Première ligne
<1/>Deuxième ligne
<2/>Troisième ligne
[=[END]=]"""
        translations = parse_llm_translation_output(output)
        is_valid, error = validate_line_count(translations, expected_count=3)
        assert is_valid is True

    def test_incomplete_output(self):
        """Test avec sortie LLM incomplète (lignes manquantes)."""
        output = """<0/>Première ligne
<2/>Troisième ligne
[=[END]=]"""
        translations = parse_llm_translation_output(output)
        is_valid, error = validate_line_count(translations, expected_count=3)
        assert is_valid is False
        assert "<1/>" in error

    def test_with_metadata_lines(self):
        """Test simulant le cas réel : LLM qui ignore les métadonnées."""
        # Source avec 47 lignes (0-46) incluant copyright
        source = "\n".join([f"<{i}/>Line {i}" for i in range(47)])

        # LLM qui ignore les lignes 17-46 (copyright, etc.)
        output = "\n".join([f"<{i}/>Ligne {i}" for i in range(17)])
        output += "\n[=[END]=]"

        translations = parse_llm_translation_output(output)
        is_valid, error = validate_line_count(
            translations, source_content=source
        )

        assert is_valid is False
        assert "Attendu: 47 lignes" in error
        assert "Reçu: 17 lignes" in error
        # Vérifier que les lignes manquantes sont mentionnées
        assert "<17/>" in error or "manquantes" in error
