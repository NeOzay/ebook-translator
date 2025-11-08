"""
Schémas TypedDict pour l'analyse littéraire (Phase 0).

Structure ChapterAnalysis : Représente une analyse complète de chapitre
avec 6 sections principales + terminologie pour glossaire.
"""

from typing import TypedDict, Literal


class CharacterEntry(TypedDict):
    """Entrée pour un personnage dans l'analyse."""

    name: str
    """Nom du personnage"""

    role: Literal["protagonist", "antagonist", "supporting"]
    """Rôle dans l'histoire"""

    first_appearance_block: int
    """Numéro du bloc où le personnage apparaît pour la première fois"""

    description: str
    """Description physique/personnalité"""

    relationships: list[str]
    """Liste des noms des personnages liés"""

    development_notes: str
    """Notes sur l'évolution du personnage dans le chapitre"""


class Characters(TypedDict):
    """Section personnages de l'analyse."""

    present: list[CharacterEntry]
    """Personnages présents physiquement dans le chapitre"""

    mentioned: list[str]
    """Personnages mentionnés mais absents"""


class Location(TypedDict):
    """Entrée pour un lieu."""

    name: str
    """Nom du lieu"""

    description: str
    """Description du lieu"""

    atmosphere: str
    """Atmosphère/ambiance du lieu"""


class Locations(TypedDict):
    """Section lieux de l'analyse."""

    primary: Location
    """Lieu principal du chapitre"""

    secondary: list[Location]
    """Lieux secondaires"""


class Conflict(TypedDict):
    """Entrée pour un conflit."""

    type: Literal["internal", "external", "interpersonal"]
    """Type de conflit"""

    description: str
    """Description du conflit"""

    parties_involved: list[str]
    """Parties impliquées (noms des personnages)"""


class PlotElements(TypedDict):
    """Section éléments narratifs."""

    main_events: list[str]
    """Événements principaux du chapitre"""

    conflicts: list[Conflict]
    """Conflits identifiés"""

    foreshadowing: list[str]
    """Éléments d'anticipation/présages"""

    revelations: list[str]
    """Révélations/découvertes importantes"""


class Theme(TypedDict):
    """Entrée pour un thème."""

    theme: str
    """Nom du thème"""

    evidence: list[str]
    """Citations/exemples supportant ce thème"""

    development: str
    """Comment ce thème se développe dans le chapitre"""


class Themes(TypedDict):
    """Section thèmes de l'analyse."""

    identified: list[Theme]
    """Thèmes identifiés"""


class NarrativeTechniques(TypedDict):
    """Section techniques narratives."""

    pov: Literal["first-person", "third-person-limited", "omniscient"]
    """Point de vue narratif"""

    tense: Literal["past", "present", "mixed"]
    """Temps verbal principal"""

    tone: str
    """Ton général (sérieux, humoristique, dramatique, etc.)"""

    narrative_devices: list[str]
    """Dispositifs narratifs utilisés (flashback, monologue intérieur, etc.)"""


class SpecializedTerm(TypedDict):
    """Entrée pour un terme spécialisé."""

    term: str
    """Terme dans la langue source"""

    context: str
    """Contexte d'utilisation"""

    category: Literal["magic", "technology", "cultural", "medical", "legal", "other"]
    """Catégorie du terme"""

    translation_notes: str
    """Considérations pour la traduction"""


class ProperNouns(TypedDict):
    """Noms propres identifiés."""

    names: list[str]
    """Noms de personnages"""

    places: list[str]
    """Noms de lieux"""

    organizations: list[str]
    """Noms d'organisations/groupes"""


class Terminology(TypedDict):
    """Section terminologie (pour glossaire)."""

    specialized_terms: list[SpecializedTerm]
    """Termes techniques/spécialisés"""

    proper_nouns: ProperNouns
    """Noms propres"""


class StylisticNotes(TypedDict):
    """Section notes stylistiques."""

    writing_style: str
    """Observations sur le style d'écriture de l'auteur"""

    recurring_motifs: list[str]
    """Motifs récurrents"""

    symbolic_elements: list[str]
    """Éléments symboliques"""

    cultural_references: list[str]
    """Références culturelles"""


class TranslationConsiderations(TypedDict):
    """Section considérations pour la traduction."""

    challenges: list[str]
    """Défis de traduction identifiés (jeux de mots, ambiguïtés, etc.)"""

    consistency_requirements: list[str]
    """Exigences de cohérence (termes à traduire uniformément, etc.)"""


class ChapterAnalysis(TypedDict):
    """
    Analyse littéraire complète d'un chapitre.

    Structure en 6 sections principales + métadonnées :
    1. Informations générales (métadonnées)
    2. Personnages (characters)
    3. Lieux (locations)
    4. Éléments narratifs (plot_elements)
    5. Thèmes (themes)
    6. Techniques narratives (narrative_techniques)
    7. Terminologie (terminology) - pour extraction glossaire
    8. Notes stylistiques (stylistic_notes)
    9. Considérations traduction (translation_considerations)

    Cycle de vie du statut :
    - "in_progress" : Analyse partielle (blocs 1 à N-1)
    - "complete" : Analyse finale (tous les blocs traités)
    """

    chapter_name: str
    """Nom/titre du chapitre"""

    analysis_version: str
    """Version du schéma d'analyse (ex: "1.0")"""

    blocks_analyzed: int
    """Nombre de blocs déjà analysés"""

    total_blocks: int
    """Nombre total de blocs dans ce chapitre"""

    status: Literal["in_progress", "complete"]
    """Statut de l'analyse"""

    # Section 1 : Personnages
    characters: Characters

    # Section 2 : Lieux
    locations: Locations

    # Section 3 : Éléments narratifs
    plot_elements: PlotElements

    # Section 4 : Thèmes
    themes: Themes

    # Section 5 : Techniques narratives
    narrative_techniques: NarrativeTechniques

    # Section 6 : Terminologie (extraction glossaire)
    terminology: Terminology

    # Section 7 : Notes stylistiques
    stylistic_notes: StylisticNotes

    # Section 8 : Considérations traduction
    translation_considerations: TranslationConsiderations
