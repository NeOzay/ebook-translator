"""
Définitions des paramètres typés pour les templates Jinja2.

Ce module centralise les TypedDicts utilisées pour le rendu des templates,
permettant une vérification de type stricte et une documentation claire
des paramètres requis pour chaque template.
"""

from typing import Any, NotRequired, TypedDict


class AnalyzeSimplifiedParams(TypedDict):
    """
    Paramètres pour analyze_simplified.jinja (Analyse simplifiée du chapitre).

    Attributes:
        chapter_name: Nom du chapitre à analyser
    """

    chapter_name: str
    target_language: str


class TranslateParams(TypedDict):
    """
    Paramètres pour translate.jinja (Phase 1 - Traduction initiale).

    Attributes:
        target_language: Code langue cible (ex: "fr", "en", "es")
        literary_context: Analyse littéraire du chapitre (optionnel, depuis Phase 0)
    """

    target_language: str
    literary_context: NotRequired[dict[str, Any]]  # Optional - AnalyseLitteraire depuis Phase 0


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
    glossaire: str
    expected_count: int
    literary_context: NotRequired[dict[str, Any]]  # Optional - AnalyseLitteraire depuis Phase 0


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
    num_lines: int


class RetryAnalysisInvalidJsonParams(TypedDict):
    chapter_name: str
    target_language: str
    json_error_message: str
    invalid_response: str


class RetryAnalysisMissingSectionsParams(TypedDict):
    chapter_name: str
    target_language: str
    missing_sections: list[str]
