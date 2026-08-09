"""
Schéma Pydantic de la sortie LLM des phases de traduction.

Source de vérité unique du format `<N/>texte … [=[END]=]` : le parsing vit
ici, dans un validateur `mode="before"` qui accepte la chaîne brute renvoyée
par le LLM. L'exécuteur (`pipeline/executor.py`) appelle donc
`payload_type.model_validate(llm_output)` directement sur le texte.

Les erreurs de format sont levées en `PydanticCustomError` dont le `type`
reprend à l'identique une valeur de `ebook_translator.validation.diagnostics.
ErreursType`. `from_pydantic_error` les reprojette ensuite en
`ValidationFailure` typées, sans que ce module ait à dépendre de
`ebook_translator` — la contrainte d'absence de cycle est portée par des
littéraux, gardés en phase par les tests de `tests/template/`.

Le `ctx` de chaque erreur respecte le diagnostic associé :
  - `missing_end_marker`   → `MissingEndMarkerDiagnostic` (`detail`)
  - `output_format_invalid`→ `OutputFormatDiagnostic` (`detail`)
  - `duplicate_indices`    → `DuplicateIndicesDiagnostic` (`duplicate_indices`)
"""

from __future__ import annotations

import re
from typing import Any, NewType, Self, override

from pydantic import model_validator
from pydantic_core import PydanticCustomError

from template.types import END_MARKER, ConvertibleModel

__all__ = ["END_MARKER", "FRAGMENT_SEPARATOR", "LineIndexed", "LineIndexedLLMResponse"]

FRAGMENT_SEPARATOR = "</>"
"""Séparateur de fragments au sein d'une même ligne.

Doublon délibéré de `ebook_translator.constants.FRAGMENT_SEPARATOR` : ce
module ne peut pas importer le paquet applicatif sans créer un cycle.
"""

_SEGMENT_RE = re.compile(r"^<(\d+)/>(.*)$", re.DOTALL)
"""Une ligne indexée : `<N/>` suivi du texte, sur une seule ligne physique."""

LineIndexed = NewType("LineIndexed", dict[int, str])
"""Vue `DT` des phases de traduction : `{index de ligne: texte}`.

`NewType` et non alias : le pipeline construit des instances explicites
(`LineIndexed({**prev, **new})`) tout en gardant un `dict` nu au runtime,
ce sur quoi reposent la sérialisation du persister et les `ContentCheck`.
"""


def _parse_raw(raw: str) -> dict[int, str]:
    """Parse la sortie LLM brute en lignes indexées.

    Les lignes sans balise `<N/>` sont du contexte : elles sont ignorées
    silencieusement. Tout ce qui suit `[=[END]=]` est également ignoré.

    Args:
        raw: Sortie textuelle du LLM.

    Returns:
        Dictionnaire `{index: texte}`, séparateurs `</>` préservés.

    Raises:
        PydanticCustomError: `missing_end_marker` si `[=[END]=]` est absent,
            `output_format_invalid` si aucun segment `<N/>` n'est reconnu,
            `duplicate_indices` si un indice apparaît plusieurs fois.
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

    lines: dict[int, str] = {}
    duplicates: list[int] = []
    for line in body.splitlines():
        match = _SEGMENT_RE.match(line.strip())
        if match is None:
            continue
        index = int(match.group(1))
        if index in lines:
            duplicates.append(index)
            continue
        lines[index] = match.group(2).strip()

    if not lines:
        raise PydanticCustomError(
            "output_format_invalid",
            "Aucun segment <N/> reconnu dans la sortie.",
            {"detail": "La sortie ne contient aucune ligne de la forme <N/>texte."},
        )

    if duplicates:
        raise PydanticCustomError(
            "duplicate_indices",
            "Indices dupliqués dans la sortie : {duplicate_indices}.",
            {"duplicate_indices": sorted(set(duplicates))},
        )

    return lines


class LineIndexedLLMResponse(ConvertibleModel[LineIndexed]):
    """Sortie LLM d'une phase de traduction, indexée par numéro de ligne.

    Accepte indifféremment la chaîne brute du LLM et la forme enveloppée
    `{"lines": {...}}` (relecture de cache, construction directe).

    Example:
        >>> m = LineIndexedLLMResponse.model_validate("<0/>Bonjour\\n[=[END]=]")
        >>> m.lines
        {0: 'Bonjour'}
    """

    lines: dict[int, str]

    @model_validator(mode="before")
    @classmethod
    def _accept_raw_text(cls, value: Any) -> Any:
        """Convertit une sortie LLM brute en `{"lines": …}` ; laisse passer le reste."""
        if isinstance(value, str):
            return {"lines": _parse_raw(value)}
        return value

    @override
    def _build_impl(self) -> LineIndexed:
        return LineIndexed(dict(self.lines))

    def line_indices(self) -> set[int]:
        """Indices de ligne présents dans la réponse."""
        return set(self.lines)

    def fragments_at(self, index: int) -> list[str]:
        """Fragments d'une ligne, découpés sur `</>`.

        Args:
            index: Indice de la ligne.

        Returns:
            Liste des fragments, dans l'ordre.

        Raises:
            KeyError: Si l'indice est absent de la réponse.
        """
        return self.lines[index].split(FRAGMENT_SEPARATOR)

    def merge(self, other: Self) -> Self:
        """Fusionne deux réponses sans muter les opérandes.

        Args:
            other: Réponse dont les lignes l'emportent sur les indices communs.

        Returns:
            Nouvelle instance portant l'union des deux jeux de lignes.
        """
        return type(self)(lines={**self.lines, **other.lines})
