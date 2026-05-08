"""Diagnostics typés pour `ValidationFailure.ctx`.

Une `TypedDict` par `ErreursType` représentant **uniquement** ce que le check
ou le validateur Pydantic produit. Aucune fuite d'environnement (pas de
`target_language`, pas de `source_text`) : ces données sont injectées plus
tard par les `build` du `RETRY_REGISTRY`.

Le couplage `ErreursType` ↔ schéma diagnostic est centralisé dans
`DIAGNOSTIC_BY_TYPE` ; un test d'invariant garantit la couverture.

Deux familles d'erreurs cohabitent :
    - schéma : structure de la sortie LLM cassée (parsing impossible). Le
      retry consiste à rejouer le prompt de phase dans son intégralité ;
      ces erreurs n'ont pas d'entrée `RETRY_REGISTRY` (voir
      `retry_registry.SCHEMA_LEVEL_ERRORS`).
    - contenu : structure OK mais fidélité au source insuffisante. Retry
      ciblé via `RETRY_REGISTRY`.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, TypedDict


class OutputFormatDiagnostic(TypedDict):
    """Sortie LLM non parsable (aucun segment `<N/>` détecté)."""

    detail: str


class MissingEndMarkerDiagnostic(TypedDict):
    """Marqueur de fin `[=[END]=]` absent."""

    detail: str


class DuplicateIndicesDiagnostic(TypedDict):
    """Plusieurs occurrences d'un même indice `<N/>` dans la sortie."""

    duplicate_indices: list[int]


class LinesMissingDiagnostic(TypedDict):
    """Lignes `<N/>` manquantes dans la traduction."""

    missing_indices: list[int]


class FragmentDiagnostic(TypedDict):
    """Nombre de séparateurs `</>` incorrect sur une ligne."""

    line: int
    expected_pairs: int
    actual_pairs: int


class PunctuationDiagnostic(TypedDict):
    """Nombre de paires de guillemets incorrect sur une ligne."""

    line: int
    expected_pairs: int
    actual_pairs: int


class SentenceDiagnostic(TypedDict):
    """Nombre de phrases incorrect sur certaines lignes."""

    invalid_indices: list[int]


class ErreursType(StrEnum):
    """Codes d'erreur stables, partagés par les `PydanticCustomError`,
    les `ContentCheck`, et le `RETRY_REGISTRY`.

    Hérite de `StrEnum` : interopérabilité directe avec les clés string
    émises par Pydantic (`ErreursType("lines_missing")`), comparaison
    naturelle avec str, sérialisation JSON triviale.
    """

    OUTPUT_FORMAT_INVALID = "output_format_invalid"
    MISSING_END_MARKER = "missing_end_marker"
    DUPLICATE_INDICES = "duplicate_indices"
    LINES_MISSING = "lines_missing"
    FRAGMENT_COUNT_MISMATCH = "fragment_count_mismatch"
    PUNCTUATION_MISMATCH = "punctuation_mismatch"
    SENTENCE_INVALID = "sentence_invalid"


DIAGNOSTIC_BY_TYPE: Mapping[ErreursType, type[Mapping[str, Any]]] = {
    ErreursType.OUTPUT_FORMAT_INVALID: OutputFormatDiagnostic,
    ErreursType.MISSING_END_MARKER: MissingEndMarkerDiagnostic,
    ErreursType.DUPLICATE_INDICES: DuplicateIndicesDiagnostic,
    ErreursType.LINES_MISSING: LinesMissingDiagnostic,
    ErreursType.FRAGMENT_COUNT_MISMATCH: FragmentDiagnostic,
    ErreursType.PUNCTUATION_MISMATCH: PunctuationDiagnostic,
    ErreursType.SENTENCE_INVALID: SentenceDiagnostic,
}
