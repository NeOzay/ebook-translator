"""
Schéma simplifié pour contexte de traduction (Phase 0).

Ce module définit le nouveau format d'analyse littéraire, optimisé pour
la traduction et réduisant la complexité de ~67% par rapport à ChapterAnalysis.
"""

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from template.types import AnalyseLitteraire

    from ebook_translator.segmentation.chunk import Scope


class ContexteTraduction(TypedDict):
    """Contexte complet pour traduction d'un chapitre.

    Ce schéma simplifié remplace ChapterAnalysis et réduit:
    - Les tokens LLM de ~67% (800-1200 → 300-400 tokens)
    - Le nombre de sections obligatoires de 78% (9 → 2)
    - La complexité du JSON de 60% (30+ champs → 12 champs)

    L'accent est mis sur:
    1. L'analyse littéraire orientée traduction (pistes concrètes)
    2. Le glossaire avec propositions de traduction directement exploitables
    """

    chapitre: str
    """Numéro ou titre du chapitre analysé"""

    analyse: AnalyseLitteraire
    """Analyse littéraire synthétique"""

    # glossaire: list[LLMTermeGlossaire]
    """Glossaire des termes importants avec traductions proposées"""

    scope: Scope
    """Portée du chunk (liste de tuples (file_name, line_number))"""


VALID_GLOSSARY_TYPES = (
    "personnage",
    "lieu",
    "creature",
    "titre",
    "objet",
    "terme_technique",
    "reference_culturelle",
)

VALID_SEXES = ("m", "f", "nc")

REQUIRED_TERME_FIELDS = (
    "terme",
    "type",
    "sexe",
    # "description_role",
    # "notes_traduction",
    "proposition_traduction",
)
