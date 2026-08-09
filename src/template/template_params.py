"""
Définitions des paramètres typés pour les templates Jinja2.

Ce module centralise les TypedDicts utilisées pour le rendu des templates,
permettant une vérification de type stricte et une documentation claire
des paramètres requis pour chaque template.
"""

from typing import Literal, NotRequired, TypedDict

from .phase.analyze_chapter_layered_models import AnalyseChapter
from .phase.glossary_models import GlossaryEntry, GlossaryMultipleValueEntry


class AnalyzeChapterParams(TypedDict):
    """
    Paramètres pour analyze_chapter_system.jinja / analyze_chapter_user.jinja.

    existing_analysis absent = premier bloc (chapter_text requis).
    existing_analysis présent = mode incrémental (current_block, total_blocks, block_text, is_last_block requis).
    """

    chapter_name: str
    target_language: str
    genre: str
    # Premier bloc
    chapter_text: str
    # Incrémental
    existing_analysis: NotRequired[str | None]
    current_block: int
    total_blocks: int
    is_last_block: bool


class AnalyzeChapterLayeredParams(TypedDict):
    """
    Paramètres pour analyze_chapter_layered_{system,user}.jinja.

    Mode dérivé des entrées :
      - bootstrap   : ni `existing_analysis` ni `previous_chapter_analysis`
      - seed        : `previous_chapter_analysis` présent, `existing_analysis` absent
      - incremental : `existing_analysis` présent

    Les snapshots `existing_analysis` et `previous_chapter_analysis` sont des
    chaînes JSON sérialisées depuis `phase.analyze_chapter_layered_models.AnalyseChapter`
    par l'orchestrateur (`AnalyseChapter.model_dump_json()`).
    """

    chapter_name: str
    chapter_text: str
    target_language: str
    genre: str
    current_block: int
    total_blocks: int
    is_last_block: bool
    existing_analysis: NotRequired[str | None]
    previous_chapter_analysis: NotRequired[str | None]


class GlossaryParams(TypedDict):
    block_text: str
    target_language: str
    genre: str
    existing_glossary: list[GlossaryMultipleValueEntry] | None
    min_reinjection_weight: int


class TranslateParams(TypedDict):
    """
    Paramètres pour translate.jinja (Phase 1 - Traduction initiale).
    """

    target_language: str
    genre: str
    source_text: str
    glossary: list[GlossaryEntry] | None
    literary_context: AnalyseChapter | None


class RefineParams(TypedDict):
    """
    Paramètres pour refine.jinja (Phase 2 - Affinage avec glossaire).
    """

    target_language: str
    genre: str
    original_text: str
    initial_translation: str

    head_context: str | None
    """Chunk précédent en paires alternées "Source : …" / "Traduction : …",
    séparées par une ligne vide. None ou chaîne vide si premier chunk.
    Format produit par l'orchestrateur (alignement source↔cible)."""

    tail_context: str | None
    """Chunk suivant, même format que head_context. None ou chaîne vide si
    dernier chunk. Suppose que la phase 1 est terminée sur le chunk suivant."""

    glossary: list[GlossaryEntry] | None
    literary_context: AnalyseChapter | None


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
    Paramètres pour retry_correct_fragments.jinja.

    Attributes:
        mode: "strict" (positions relatives préservées) ou "flexible" (positions adaptées à la grammaire cible)
    """

    target_language: str
    original_text: str
    incorrect_translation: str
    expected_separators: int
    actual_separators: int
    mode: Literal["strict", "flexible"]


class RetryPunctuationParams(TypedDict):
    """
    Paramètres pour retry_punctuation.jinja (Correction paires de guillemets).

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

    Attributes:
        target_language: Code langue cible (ex: "fr", "en")
        original_text: Texte source original avec numérotation sélective
        previous_translation: Traduction initiale (Phase 1) avec numérotation sélective
        missing_indices: Liste formatée des indices invalides (ex: "<5/>, <7/>, <12/>")
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
