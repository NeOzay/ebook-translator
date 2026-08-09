"""
Schéma Pydantic de la sortie LLM de la phase glossaire.

Source de vérité unique du format produit par le LLM : un tableau délimité,
une ligne par terme, sans enveloppe JSON.

    alice|personnage|f|Alice
    white rabbit|creature|m|Lapin Blanc
    [=[END]=]

Le format tabulaire remplace le JSON `{"colonnes": …, "entrees": […]}` : à
structure identique, l'enveloppe JSON coûtait environ deux fois plus de
tokens **de sortie** par entrée, les plus chers du pipeline. Le parsing vit
donc ici, dans un validateur `mode="before"` acceptant la chaîne brute, et la
phase passe par `LLM.query()` plutôt que par Instructor.

**Tolérance aux lignes malformées** — une ligne dont la cardinalité n'est pas
`_NB_COLONNES`, ou dont `type`/`sexe` sort des valeurs autorisées, est écartée
avec un `WARNING` : le glossaire est un agrégat pondéré sur tout le livre, où
perdre un terme est sans conséquence, alors qu'un retry coûterait précisément
les tokens que ce format économise. Les lignes écartées restent lisibles dans
`lignes_rejetees`. Seules deux situations font échouer le chunk entier : la
génération tronquée (marqueur de fin absent) et la réponse dont *aucune* ligne
n'est exploitable — un modèle qui a ignoré le format.

Pour ajouter ou renommer une colonne du tableau :
  1. mettre à jour `_GLOSSARY_COLUMNS` (l'ordre fait foi),
  2. étendre `Entree` et `LLMTermeGlossary`,
  3. ajuster `_parse_line` si la colonne porte une contrainte de valeur,
  4. mettre à jour `glossary_system.jinja` (format montré au LLM).
"""

import logging
import re
from typing import Annotated, Any, Literal, NotRequired, TypedDict, override

from pydantic import ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from template.types import END_MARKER, ConvertibleModel, NormStr, WsStr

logger = logging.getLogger(__name__)

GlossaryEntryType = Literal[
    "personnage",
    "lieu",
    "creature",
    "appellation",
    "organisation",
    "objet",
    "terme_technique",
    "reference_culturelle",
]
type _NormGlossaryEntryType = Annotated[GlossaryEntryType, NormStr]

GlossaryEntrySexe = Literal["m", "f", "nc"]
type _NormGlossaryEntrySexe = Annotated[GlossaryEntrySexe, NormStr]

GLOSSARY_SEPARATOR = "|"
"""Délimiteur de colonnes.

Choisi parce qu'il n'apparaît pas en prose littéraire : aucune règle
d'échappement n'est nécessaire, donc pas de guillemets réintroduits et un
format à géométrie constante. Une ligne qui en contiendrait un de trop est
écartée par le contrôle de cardinalité.
"""

LLMColonneOrder = tuple[
    Literal["terme"],
    Literal["type"],
    Literal["sexe"],
    Literal["proposition_traduction"],
]

GLOSSARY_COLUMNS: LLMColonneOrder = (
    "terme",
    "type",
    "sexe",
    "proposition_traduction",
)
"""Ordre des colonnes. Porté par le format lui-même, plus par un champ.

Reste exposé pour la documentation du prompt et les messages d'erreur.
"""

GLOSSARY_TYPES_AUTORISES: frozenset[GlossaryEntryType] = frozenset(
    GlossaryEntryType.__args__
)

GLOSSARY_SEXES_AUTORISES: frozenset[GlossaryEntrySexe] = frozenset(
    GlossaryEntrySexe.__args__
)

_TERME_INDEX: int = GLOSSARY_COLUMNS.index("terme")
_TYPE_INDEX: int = GLOSSARY_COLUMNS.index("type")
_SEXE_INDEX: int = GLOSSARY_COLUMNS.index("sexe")
_PROPOSITION_INDEX: int = GLOSSARY_COLUMNS.index("proposition_traduction")
_NB_COLONNES: int = len(GLOSSARY_COLUMNS)


class LLMTermeGlossary(TypedDict):
    """Représente un terme du glossaire tel que proposé par le LLM."""

    terme: str
    type: GlossaryEntryType
    sexe: GlossaryEntrySexe
    proposition_traduction: str


type Entree = tuple[NormStr, _NormGlossaryEntryType, _NormGlossaryEntrySexe, WsStr]
"""Ligne validée. Seul le terme est normalisé — il sert de clé au glossaire ;
la traduction proposée garde sa casse, c'est elle qui sera écrite dans le texte."""


_PUCE_RE = re.compile(r"^(?:[-*•+]|\d+[.)])\s+")
"""Puce ou numérotation en tête de ligne.

Retirée plutôt qu'écartée : la ligne reste bien formée à quatre champs, et
l'ingérer telle quelle polluerait le glossaire d'un terme `- alice` — une
erreur silencieuse, là où le rejet ne coûte qu'un terme.
"""


def _parse_line(line: str) -> Entree | None:
    """Valide une ligne du tableau.

    Args:
        line: Ligne brute, déjà débarrassée de ses espaces de bord.

    Returns:
        L'entrée à quatre champs, ou `None` si la ligne doit être écartée.
    """
    champs = [
        champ.strip() for champ in _PUCE_RE.sub("", line).split(GLOSSARY_SEPARATOR)
    ]
    if len(champs) != _NB_COLONNES:
        return None

    terme = champs[_TERME_INDEX]
    type_ = champs[_TYPE_INDEX].lower()
    sexe = champs[_SEXE_INDEX].lower()
    proposition = champs[_PROPOSITION_INDEX]

    if not terme or not proposition:
        return None
    if type_ not in GLOSSARY_TYPES_AUTORISES or sexe not in GLOSSARY_SEXES_AUTORISES:
        return None

    return (terme, type_, sexe, proposition)  # pyright: ignore[reportReturnType]


def _parse_raw(raw: str) -> dict[str, Any]:
    """Parse la sortie LLM brute en entrées de glossaire.

    Les lignes vides sont ignorées ; les lignes malformées sont écartées et
    collectées dans `lignes_rejetees`. Tout ce qui suit `[=[END]=]` est ignoré.

    Args:
        raw: Sortie textuelle du LLM.

    Returns:
        Les champs du modèle, prêts pour la validation Pydantic.

    Raises:
        PydanticCustomError: `missing_end_marker` si `[=[END]=]` est absent
            (génération vraisemblablement tronquée), `output_format_invalid`
            si la réponse contient des lignes mais qu'aucune n'est exploitable.
    """
    text = raw.strip()

    if END_MARKER not in text:
        raise PydanticCustomError(
            "missing_end_marker",
            "Marqueur de fin {end_marker} absent de la sortie.",
            {
                "detail": f"La sortie ne contient pas {END_MARKER}.",
                "end_marker": END_MARKER,
            },
        )

    body, _, _ = text.partition(END_MARKER)

    entrees: list[Entree] = []
    rejetees: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        entree = _parse_line(stripped)
        if entree is None:
            rejetees.append(stripped)
        else:
            entrees.append(entree)

    if rejetees:
        logger.warning(
            "Glossaire : %d ligne(s) écartée(s) sur %d. Première : %r",
            len(rejetees),
            len(rejetees) + len(entrees),
            rejetees[0],
        )

    # Un bloc sans terme notable est légitime et donne une liste vide ; une
    # réponse dont *toutes* les lignes sont illisibles signale en revanche un
    # modèle qui a ignoré le format.
    if not entrees and rejetees:
        raise PydanticCustomError(
            "output_format_invalid",
            "Aucune ligne exploitable dans la sortie du glossaire.",
            {
                "detail": (
                    f"Aucune des {len(rejetees)} ligne(s) ne respecte le format "
                    f"{GLOSSARY_SEPARATOR.join(GLOSSARY_COLUMNS)}."
                )
            },
        )

    return {"entrees": entrees, "lignes_rejetees": rejetees}


class LLMGlossaryModel(ConvertibleModel[list[LLMTermeGlossary]]):
    """Tableau du glossaire, une ligne délimitée par terme.

    Accepte indifféremment la sortie brute du LLM et la forme enveloppée
    `{"entrees": [...]}` (relecture de cache, construction directe).

    Example:
        >>> raw = "alice|personnage|f|Alice\\n[=[END]=]"
        >>> LLMGlossaryModel.model_validate(raw).build()
        [{'terme': 'alice', 'type': 'personnage', 'sexe': 'f', 'proposition_traduction': 'Alice'}]
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    entrees: list[Entree] = Field(
        description=(
            "Entrées du glossaire, chacune à "
            f"{_NB_COLONNES} champs dans l'ordre {list(GLOSSARY_COLUMNS)}."
        ),
    )

    lignes_rejetees: tuple[str, ...] = Field(
        default=(),
        description="Lignes écartées au parsing, conservées pour diagnostic.",
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_raw_text(cls, value: Any) -> Any:
        """Convertit une sortie LLM brute en champs du modèle ; laisse passer le reste."""
        if isinstance(value, str):
            return _parse_raw(value)
        return value

    @override
    def _build_impl(self) -> list[LLMTermeGlossary]:
        final_list: list[LLMTermeGlossary] = []
        for entree in self.entrees:
            terme, type_, sexe, proposition_traduction = entree
            final_list.append(
                {
                    "terme": terme.strip(),
                    "type": type_,
                    "sexe": sexe,
                    "proposition_traduction": proposition_traduction.strip(),
                },
            )
        return final_list


class GlossaryEntry(TypedDict):
    """Représente un terme exporté depuis le glossaire"""

    terme: str
    traduction: str
    sexe: GlossaryEntrySexe
    type: GlossaryEntryType
    weight: NotRequired[
        int
    ]  # nombre de fois que le terme a été proposé par le LLM. Les termes fournis par l'utilisateur n'ont pas de poids.
    confidence: Literal["low", "medium", "high"]


class GlossaryMultipleValueEntry(TypedDict):
    """Représente un terme exporté depuis le glossaire avec plusieurs propositions de traduction possibles pondérées."""

    terme: str
    traductions: list[tuple[str, int]]
    sexes: list[tuple[GlossaryEntrySexe, int]]
    types: list[tuple[GlossaryEntryType, int]]
    weight: int
    confidence: Literal["low", "medium", "high"]
