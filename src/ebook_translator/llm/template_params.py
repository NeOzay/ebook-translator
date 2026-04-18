"""
Définitions des paramètres typés pour les templates Jinja2.

Ce module centralise les TypedDicts utilisées pour le rendu des templates,
permettant une vérification de type stricte et une documentation claire
des paramètres requis pour chaque template.
"""

from typing import TYPE_CHECKING, Literal, TypedDict

from ebook_translator.glossary import GlossaryEntry, GlossaryMultipleValueEntry

if TYPE_CHECKING:
    from ebook_translator.validator.translation_context import AnalyseLitteraire


class AnalyzeSimplifiedParams(TypedDict):
    """
    Paramètres pour analyze_simplified.jinja (Analyse simplifiée du chapitre).

    Attributes:
        chapter_name: Nom du chapitre à analyser
    """

    chapter_name: str
    target_language: str
    chapter_text: str
    genre: str


class AnalyzeIncremental(TypedDict):
    chapter_name: str
    current_block: int
    total_blocks: int
    partial_analysis_json: str
    block_text: str
    is_last_block: bool
    genre: str
    target_language: str


class GlossaryParams(TypedDict):
    block_text: str
    target_language: str
    genre: str
    existing_glossary: list[GlossaryMultipleValueEntry] | None


class TranslateParams(TypedDict):
    """
    Paramètres pour translate.jinja (Phase 1 - Traduction initiale).
    """

    target_language: str
    source_text: str
    glossary: list[GlossaryEntry] | None
    literary_context: AnalyseLitteraire | None


class RefineParams(TypedDict):
    """
    Paramètres pour refine.jinja (Phase 2 - Affinage avec glossaire).

    Attributes:
        target_language: Code langue cible (ex: "fr", "en")
        original_text: Texte source original formaté (head + body + tail)
        initial_translation: Traduction Phase 1 formatée (head + body + tail)
        glossaire: Export du glossaire appris en Phase 1
        expected_count: Nombre de lignes numérotées <N/> attendues dans le body
        literary_context: Analyse littéraire du chapitre (optionnel, depuis Phase 0)
    """

    target_language: str
    original_text: str
    initial_translation: str
    head_context: str
    tail_context: str
    glossary: list[GlossaryEntry] | None
    literary_context: AnalyseLitteraire | None


class MissingLinesParams(TypedDict):
    """
    Paramètres pour retry_missing_lines_targeted.jinja (Correction lignes manquantes).

    Attributes:
        target_language: Code langue cible (ex: "fr", "en")
        missing_indices: Liste des indices de lignes manquantes à traduire
        source_content: Contenu source avec seulement lignes manquantes numérotées
        error_message: Message d'erreur contextuel listant les lignes manquantes
    """

    target_language: str
    missing_indices: list[int]
    source_content: str
    error_message: str


class RetryFragmentsParams(TypedDict):
    """
    Paramètres pour retry_fragments.jinja (Retry fragments - Mode NORMAL).

    Utilisé pour corriger le nombre de séparateurs `</>` incorrect.
    Mode NORMAL : préservation stricte des positions relatives.

    Attributes:
        target_language: Code langue cible (ex: "fr", "en")
        original_text: Texte source original
        incorrect_translation: Traduction produite avec nombre incorrect de séparateurs
        expected_separators: Nombre de séparateurs `</>` attendus
        actual_separators: Nombre de séparateurs `</>` trouvés dans la traduction
    """

    target_language: str
    original_text: str
    incorrect_translation: str
    expected_separators: int
    actual_separators: int
    mode: Literal["strict", "flexible"]


class RetryFragmentsFlexibleParams(TypedDict):
    """
    Paramètres pour retry_fragments_flexible.jinja (Retry fragments - Mode FLEXIBLE).

    Utilisé pour corriger le nombre de séparateurs `</>` incorrect.
    Mode FLEXIBLE : placement libre des séparateurs (même nombre).

    Attributes:
        target_language: Code langue cible (ex: "fr", "en")
        original_text: Texte source original
        incorrect_translation: Traduction produite avec nombre incorrect de séparateurs
        expected_separators: Nombre de séparateurs `</>` attendus
        actual_separators: Nombre de séparateurs `</>` trouvés dans la traduction
    """

    target_language: str
    original_text: str
    incorrect_translation: str
    expected_separators: int
    actual_separators: int


class RetryPunctuationParams(TypedDict):
    """
    Paramètres pour retry_punctuation.jinja (Correction paires de guillemets).

    Utilisé pour corriger le nombre de paires de guillemets incorrect
    (dialogues fusionnés, interruptions narratives perdues).

    Attributes:
        target_language: Code langue cible (ex: "fr", "en")
        original_text: Texte source original
        incorrect_translation: Traduction avec nombre incorrect de paires
        expected_pairs: Nombre de paires de guillemets attendues
        actual_pairs: Nombre de paires trouvées dans la traduction
    """

    target_language: str
    original_text: str
    incorrect_translation: str
    expected_pairs: int
    actual_pairs: int


class RetrySentenceParams(TypedDict):
    """
    Paramètres pour retry_sentence.jinja (Correction nombre de phrases).

    Utilisé pour corriger les traductions avec un nombre incorrect de phrases,
    typiquement lors du raffinage où le LLM tronque le contenu au lieu de
    l'améliorer. Fournit les deux traductions (initiale + raffinée) pour
    permettre au LLM de comprendre ce qui a été perdu.

    Attributes:
        target_language: Code langue cible (ex: "fr", "en")
        original_text: Texte source original avec numérotation sélective
        previous_translation: Traduction initiale (Phase 1) avec numérotation sélective
        missing_indices: Liste formatée des indices invalides (ex: "<5/>, <7/>, <12/>")
        num_lines: Nombre de lignes invalides à corriger
    """

    target_language: str
    original_text: str
    previous_translation: str
    missing_indices: str


class RetryAnalysisInvalidJsonParams(TypedDict):
    chapter_name: str
    target_language: str
    json_error_message: str
    invalid_response: str


class RetryAnalysisMissingSectionsParams(TypedDict):
    chapter_name: str
    target_language: str
    missing_sections: list[str]
    incomplete_response: str
    chapter_text: str
