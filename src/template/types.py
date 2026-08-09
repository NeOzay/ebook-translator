"""
Types partagés entre les templates Jinja2 et le pipeline de traduction.

Ce module contient les TypedDicts qui définissent les structures de données
injectées dans les templates ou produites par le LLM.
Aucune dépendance sur ebook_translator — importable partout sans circularité.
"""

from abc import abstractmethod
from functools import cache
from typing import Annotated, Any, Literal, TypedDict, final, get_type_hints

from pydantic import BaseModel, BeforeValidator, TypeAdapter

END_MARKER = "[=[END]=]"
"""Marqueur de fin de sortie LLM, commun à tous les formats textuels.

Partagé par les phases de traduction et la phase glossaire : il signale que
la réponse est complète et permet de détecter une génération tronquée.
"""


class ConvertibleModel[TD](BaseModel):
    """BaseModel qui sait se convertir en un TypedDict cible."""

    _cached_build: TD | None = None

    @abstractmethod
    def _build_impl(self) -> TD: ...

    @final
    def build(self) -> TD:
        if self._cached_build is None:
            object.__setattr__(self, "_cached_build", self._build_impl())
        return self._cached_build  # pyright: ignore[reportReturnType]

    def serialized_build(self, *, indent: int | None = None) -> str:
        return self.target_adapter().dump_json(self.build(), indent=indent).decode()

    @classmethod
    def deserialize(cls, raw: str | bytes) -> TD:
        return cls.target_adapter().validate_json(raw)

    @classmethod
    @cache
    def target_adapter(cls) -> TypeAdapter[TD]:
        """TypeAdapter pour le TypedDict cible.

        Le type est lu sur `_build_impl` et non sur `build` : `build` est
        `@final` et annoté `-> TD`, une variable de type que `get_type_hints`
        ne résout jamais pour la sous-classe — l'adapter dégénérerait alors
        en `Any` et laisserait passer les données sans coercition (clés de
        dictionnaire restées `str` à la relecture JSON, par exemple).
        `_build_impl` est abstrait, donc toujours surchargé avec le type
        concret, et résolu dans le module de la sous-classe.
        """
        target_type = get_type_hints(cls._build_impl)["return"]
        return TypeAdapter(target_type)


def normalize_string(value: object) -> object:
    """Normalise une chaîne pour comparaison (minuscules, espaces réduits)."""
    return " ".join(value.strip().lower().split()) if isinstance(value, str) else value


def normalize_whitespace(value: object) -> object:
    """Réduit les espaces d'une chaîne, sans toucher à la casse.

    Pour les champs dont la valeur est *affichée* plutôt que comparée : une
    traduction proposée par le LLM garde sa casse, seule la clé qui l'indexe
    est normalisée.
    """
    return " ".join(value.split()) if isinstance(value, str) else value


def normalize_tuple(v: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(x.strip().lower() if isinstance(x, str) else x for x in v)


NormStrValidator = BeforeValidator(normalize_string)
WsStrValidator = BeforeValidator(normalize_whitespace)
NormTupleValidator = BeforeValidator(normalize_tuple)

NormStr = Annotated[str, NormStrValidator]

WsStr = Annotated[str, WsStrValidator]
"""Chaîne aux espaces réduits, casse préservée."""


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
    """Liste de pistes concrètes pour la traduction."""
