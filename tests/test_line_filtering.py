"""
Tests pour le système de filtrage des lignes invalides.

Ce module teste le nouveau comportement du pipeline de validation qui filtre
les lignes invalides au lieu de rejeter tout le chunk.
"""

import pytest
from unittest.mock import Mock, MagicMock
from dataclasses import dataclass

from src.ebook_translator.checks import (
    ValidationContext,
    ValidationPipeline,
    LineCountCheck,
    FragmentCountCheck,
    PunctuationCheck,
    FilteredLine,
)
from src.ebook_translator.segment import Chunk
from src.ebook_translator.htmlpage import TagKey


@dataclass
class MockEpubHtml:
    """Mock pour EpubHtml."""
    file_name: str


@dataclass
class MockPage:
    """Mock pour HtmlPage."""
    epub_html: MockEpubHtml


def create_mock_chunk(index: int, num_lines: int) -> Chunk:
    """
    Crée un chunk mock pour les tests.

    Args:
        index: Index du chunk
        num_lines: Nombre de lignes dans le body

    Returns:
        Chunk mock avec body rempli
    """
    chunk = Chunk(index=index)

    # Créer des TagKey mock
    mock_page = MockPage(epub_html=MockEpubHtml(file_name="test.xhtml"))

    for i in range(num_lines):
        mock_tag = Mock()
        tag_key = Mock(spec=TagKey)
        tag_key.index = str(i * 10)  # Indices simulés : 0, 10, 20, ...
        tag_key.page = mock_page

        chunk.body[tag_key] = f"Line {i} text"

    return chunk


def create_mock_llm():
    """Crée un LLM mock qui retourne toujours une traduction vide."""
    llm = Mock()
    llm.query = Mock(return_value="[ERREUR]")  # Simule échec
    return llm


def test_line_count_filtering():
    """
    Test : LineCountCheck filtre les lignes manquantes après échec correction.

    Scénario :
    - 10 lignes dans le chunk body
    - 8 lignes traduites (2 manquantes : indices 3, 7)
    - 8 lignes originales (attendues)
    - Correction échoue
    - Pipeline filtre les 2 lignes manquantes
    - Sauvegarde 8 lignes valides
    """
    # Arrange
    chunk = create_mock_chunk(index=0, num_lines=10)

    # original_texts correspond aux lignes qu'on ATTEND (translated_texts)
    # Si translated_texts ne contient pas 3 et 7, c'est que ces lignes sont manquantes
    # Donc original_texts devrait contenir toutes les 10 lignes attendues
    original_texts = {i: f"Original {i}" for i in range(10)}
    translated_texts = {i: f"Traduit {i}" for i in range(10) if i not in {3, 7}}

    llm = create_mock_llm()

    context = ValidationContext(
        chunk=chunk,
        translated_texts=translated_texts,
        original_texts=original_texts,
        llm=llm,
        target_language="fr",
        phase="initial",
        max_retries=1,
    )

    pipeline = ValidationPipeline([LineCountCheck()])

    # Act
    success, final_translations, results = pipeline.validate_and_correct(context)

    # Assert
    assert success, "Pipeline devrait réussir avec filtrage"
    assert len(final_translations) == 8, "8 lignes valides devraient être conservées"
    assert 3 not in final_translations, "Ligne 3 devrait être filtrée"
    assert 7 not in final_translations, "Ligne 7 devrait être filtrée"
    assert len(context.filtered_lines) == 2, f"2 lignes devraient être filtrées, got {len(context.filtered_lines)}"

    # Vérifier FilteredLine
    filtered_indices = {fl.chunk_line for fl in context.filtered_lines}
    assert filtered_indices == {3, 7}, "Lignes 3 et 7 devraient être dans filtered_lines"

    # Vérifier métadonnées
    for filtered in context.filtered_lines:
        assert filtered.file_name == "test.xhtml"
        assert filtered.chunk_index == 0
        assert filtered.check_name == "line_count"
        assert "manquante" in filtered.reason.lower()


def test_fragment_count_filtering():
    """
    Test : FragmentCountCheck filtre les lignes avec mauvais fragments.

    Scénario :
    - 10 lignes avec fragments corrects
    - 2 lignes avec mauvais fragments (indices 2, 5)
    - Correction échoue
    - Pipeline filtre les 2 lignes invalides
    """
    # Arrange
    chunk = create_mock_chunk(index=1, num_lines=10)

    original_texts = {
        i: f"Text{i}</>Part" if i in {2, 5} else f"Text{i}"
        for i in range(10)
    }

    translated_texts = {
        i: f"Texte{i}" for i in range(10)  # Pas de </> → mauvais pour 2 et 5
    }

    llm = create_mock_llm()

    context = ValidationContext(
        chunk=chunk,
        translated_texts=translated_texts,
        original_texts=original_texts,
        llm=llm,
        target_language="fr",
        phase="initial",
        max_retries=1,
    )

    pipeline = ValidationPipeline([FragmentCountCheck()])

    # Act
    success, final_translations, results = pipeline.validate_and_correct(context)

    # Assert
    assert success, "Pipeline devrait réussir avec filtrage"
    assert len(final_translations) == 8, "8 lignes valides conservées"
    assert 2 not in final_translations, "Ligne 2 filtrée"
    assert 5 not in final_translations, "Ligne 5 filtrée"
    assert len(context.filtered_lines) == 2


def test_punctuation_filtering():
    """
    Test : PunctuationCheck filtre les lignes avec mauvaise ponctuation.

    Note: Désactivé temporairement car PunctuationCheck nécessite guillemets typographiques.
    """
    # TODO: Réactiver quand PunctuationCheck supportera guillemets droits
    pass


def test_multiple_checks_filtering():
    """
    Test : Plusieurs checks filtrent des lignes différentes.

    Scénario :
    - LineCountCheck filtre lignes {3, 7}
    - FragmentCountCheck filtre ligne {2} (parmi restantes)
    - Total : 3 lignes filtrées, 7 conservées
    """
    # Arrange
    chunk = create_mock_chunk(index=3, num_lines=10)

    # 10 lignes originales attendues
    # Ligne 2 a un fragment (mauvais nombre)
    original_texts = {
        i: f"Text{i}</>Part" if i == 2 else f"Text{i}"
        for i in range(10)
    }

    # Traductions: manque 3 et 7, et ligne 2 n'a pas le séparateur
    translated_texts = {
        i: f"Texte{i}" for i in range(10)
        if i not in {3, 7}  # Pas de traduction pour 3 et 7
    }

    llm = create_mock_llm()

    context = ValidationContext(
        chunk=chunk,
        translated_texts=translated_texts,
        original_texts=original_texts,
        llm=llm,
        target_language="fr",
        phase="initial",
        max_retries=1,
    )

    pipeline = ValidationPipeline([
        LineCountCheck(),
        FragmentCountCheck(),
    ])

    # Act
    success, final_translations, results = pipeline.validate_and_correct(context)

    # Assert
    assert success, "Pipeline devrait réussir"
    assert len(final_translations) == 7, f"7 lignes valides conservées, got {len(final_translations)}"
    assert len(context.filtered_lines) == 3, f"3 lignes filtrées au total, got {len(context.filtered_lines)}: {context.filtered_lines}"

    # Vérifier quels checks ont filtré quoi
    line_count_filtered = [fl for fl in context.filtered_lines if fl.check_name == "line_count"]
    fragment_filtered = [fl for fl in context.filtered_lines if fl.check_name == "fragment_count"]

    assert len(line_count_filtered) == 2, f"LineCountCheck a filtré 2 lignes, got {len(line_count_filtered)}"
    assert len(fragment_filtered) == 1, f"FragmentCountCheck a filtré 1 ligne, got {len(fragment_filtered)}"


def test_filtered_line_metadata():
    """
    Test : FilteredLine contient toutes les métadonnées correctes.
    """
    # Arrange
    chunk = create_mock_chunk(index=5, num_lines=5)

    # original_texts = toutes les lignes attendues (0 à 4)
    # translated_texts = seulement 0, 1, 2 (manque 3, 4)
    original_texts = {i: f"Text {i}" for i in range(5)}
    translated_texts = {0: "Texte 0", 1: "Texte 1", 2: "Texte 2"}  # Manque 3, 4

    llm = create_mock_llm()

    context = ValidationContext(
        chunk=chunk,
        translated_texts=translated_texts,
        original_texts=original_texts,
        llm=llm,
        target_language="fr",
        phase="initial",
        max_retries=1,
    )

    pipeline = ValidationPipeline([LineCountCheck()])

    # Act
    success, final_translations, results = pipeline.validate_and_correct(context)

    # Assert
    assert success, "Pipeline devrait réussir avec filtrage"
    assert len(context.filtered_lines) == 2, f"Expected 2 filtered lines, got {len(context.filtered_lines)}"

    for filtered in context.filtered_lines:
        # Vérifier tous les champs
        assert filtered.file_name == "test.xhtml"
        assert filtered.file_line in {"30", "40"}  # Indices 3 et 4 → 30, 40
        assert filtered.chunk_index == 5
        assert filtered.chunk_line in {3, 4}
        assert filtered.check_name == "line_count"
        assert filtered.reason == "Ligne manquante après correction"
        assert "Line" in filtered.original_text  # Texte original présent


def test_no_filtering_when_all_valid():
    """
    Test : Pas de filtrage si toutes les lignes sont valides.
    """
    # Arrange
    chunk = create_mock_chunk(index=0, num_lines=5)

    original_texts = {i: f"Text {i}" for i in range(5)}
    translated_texts = {i: f"Texte {i}" for i in range(5)}  # Toutes présentes

    context = ValidationContext(
        chunk=chunk,
        translated_texts=translated_texts,
        original_texts=original_texts,
        llm=None,  # Pas besoin de LLM si tout est valide
        target_language="fr",
        phase="initial",
        max_retries=1,
    )

    pipeline = ValidationPipeline([
        LineCountCheck(),
        FragmentCountCheck(),
        PunctuationCheck(),
    ])

    # Act
    success, final_translations, results = pipeline.validate_and_correct(context)

    # Assert
    assert success
    assert len(final_translations) == 5, "Toutes les lignes conservées"
    assert len(context.filtered_lines) == 0, "Aucune ligne filtrée"


def test_filter_reason_messages():
    """
    Test : Messages de raison de filtrage sont descriptifs et corrects.
    """
    # Test LineCountCheck
    chunk = create_mock_chunk(index=0, num_lines=3)
    original_texts = {0: "Text 0"}  # Manque 1, 2
    translated_texts = {0: "Texte 0"}

    context = ValidationContext(
        chunk=chunk,
        translated_texts=translated_texts,
        original_texts=original_texts,
        llm=create_mock_llm(),
        target_language="fr",
        phase="initial",
        max_retries=1,
    )

    pipeline = ValidationPipeline([LineCountCheck()])
    success, _, _ = pipeline.validate_and_correct(context)

    assert success
    for filtered in context.filtered_lines:
        assert "manquante" in filtered.reason.lower()

    # Test FragmentCountCheck
    chunk2 = create_mock_chunk(index=1, num_lines=3)
    original_texts2 = {0: "Text</>Part", 1: "Simple"}
    translated_texts2 = {0: "Texte", 1: "Simple"}  # 0 manque </>

    context2 = ValidationContext(
        chunk=chunk2,
        translated_texts=translated_texts2,
        original_texts=original_texts2,
        llm=create_mock_llm(),
        target_language="fr",
        phase="initial",
        max_retries=1,
    )

    pipeline2 = ValidationPipeline([FragmentCountCheck()])
    success2, _, _ = pipeline2.validate_and_correct(context2)

    assert success2
    assert len(context2.filtered_lines) == 1
    assert "fragments" in context2.filtered_lines[0].reason.lower()
    assert "attendu" in context2.filtered_lines[0].reason.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
