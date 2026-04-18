"""
Schéma simplifié pour contexte de traduction (Phase 0).

Ce module définit le nouveau format d'analyse littéraire, optimisé pour
la traduction et réduisant la complexité de ~67% par rapport à ChapterAnalysis.
"""

from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from ebook_translator.segmentation.chunk import Scope

type AnalyseLitteraireKey = Literal[
    "resume_narratif",
    "tonalite_ambiance",
    "style_ecriture",
    "themes_images_cles",
    "references_culturelles",
    "pistes_traduction",
]


class AnalyseLitteraire(TypedDict):
    """Analyse littéraire synthétique du chapitre."""

    resume_narratif: str
    """Résumé narratif (max 5 lignes)"""

    tonalite_ambiance: str
    """Tonalité et ambiance générale"""

    style_ecriture: str
    """Style d'écriture observé"""

    themes_images_cles: str
    """Thèmes et images clés du chapitre"""

    references_culturelles: str
    """Références culturelles présentes"""

    pistes_traduction: list[str]
    """Liste de pistes concrètes pour la traduction.

    Exemples:
    - "Préserver le ton ironique et les dialogues vifs"
    - "Adapter l'idiome 'break a leg' en équivalent français"
    - "Conserver le rythme rapide des phrases courtes"
    """


TermType = Literal[
    "personnage",
    "lieu",
    "creature",
    "titre",
    "objet",
    "terme_technique",
    "reference_culturelle",
]
SexeType = Literal["m", "f", "nc"]


class TermeGlossaire(TypedDict):
    """Terme à inclure dans le glossaire avec sa traduction proposée."""

    terme: str
    """Terme original dans la langue source"""

    type: TermType | str
    """Type de terme pour catégorisation"""

    sexe: SexeType | str
    """Sexe pour personnages/créatures (m=masculin, f=féminin, nc=non concerné)"""

    # description_role: str
    """Description brève ou rôle du terme dans le récit"""

    # notes_traduction: str
    """Notes pour guider la décision de traduction"""

    proposition_traduction: str
    """Proposition de traduction UNIQUE (un seul terme, pas de liste).

    """


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

    # glossaire: list[TermeGlossaire]
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
