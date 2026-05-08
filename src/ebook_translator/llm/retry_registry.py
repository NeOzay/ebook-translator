"""Registre `ErreursType` → entrée de retry (template, params, mode de fusion).

Source de vérité unique pour le mapping erreur-de-validation → prompt de
correction. Le worker de validation lit ce registre pour décider quel
template Jinja rendre, comment construire les paramètres typés, et comment
fusionner la nouvelle sortie LLM avec la dernière sortie partielle.

Couverture invariant : tout `ErreursType` de **niveau contenu** DOIT avoir
une entrée ici. Les erreurs **schéma** (`SCHEMA_LEVEL_ERRORS`) ne passent
pas par ce registre : elles déclenchent un re-rendu complet du prompt de
phase, dont seul `PhaseBase[M]` connaît le template à partir de l'étape 5.

Note étape 2 : les `build` sont des stubs. Ils seront câblés à partir de
l'étape 5 quand `PhaseBase[M]` connaîtra `ChunkSource` et `PhaseConfig`.
Phase 0 / glossaire passent par Instructor (Pydantic + tools) et n'ont pas
d'entrée retry texte.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from template.template_params import (
    MissingLinesParams,
    RetryFragmentsParams,
    RetryPunctuationParams,
    RetrySentenceParams,
)

from ..validation.diagnostics import ErreursType
from ..validation.failure import ValidationFailure
from ..validation.retry_strategy import RetryStrategy
from .template_renderers import RetryTemplate


def _todo_build(
    failure: ValidationFailure[Mapping[str, Any]], source: Any, config: Any
) -> Any:
    """Stub pour les `build` du registre.

    Sera remplacé phase par phase à partir de l'étape 5 quand `PhaseBase[M]`
    et le worker unifié connaîtront `ChunkSource` et `PhaseConfig`. Retourne
    `Any` pour rester compatible avec n'importe quel `RetryEntry[D, P]`.
    """

    raise NotImplementedError(
        "RetryEntry.build sera câblé à partir de l'étape 5 (PhaseBase[M])."
    )


@dataclass(frozen=True)
class RetryEntry[D: Mapping[str, Any], P: Mapping[str, Any]]:
    """Décrit comment retraiter une `ValidationFailure` donnée.

    Attributes:
        template: Membre `RetryTemplate` qui résout la paire system/user.
        params_type: `TypedDict` des paramètres attendus par le template.
            Le retour de `build` doit être assignable à ce type.
        build: Fonction qui combine le diagnostic typé, la source du chunk
            et la config de phase pour produire un `params_type` complet.
        mode: Sémantique de fusion entre la dernière sortie partielle et la
            réponse du retry. `replace` écrase entièrement, `merge` fusionne
            au niveau du modèle (utilisé pour les retries ciblés comme
            `LINES_MISSING` ou `SENTENCE_INVALID`).
    """

    template: RetryTemplate
    params_type: type[P]
    build: Callable[[ValidationFailure[D], Any, Any], P]
    mode: Literal["replace", "merge"]


SCHEMA_LEVEL_ERRORS: frozenset[ErreursType] = frozenset(
    {
        ErreursType.OUTPUT_FORMAT_INVALID,
        ErreursType.MISSING_END_MARKER,
        ErreursType.DUPLICATE_INDICES,
    }
)
"""Erreurs structurelles de la sortie LLM. Pas de retry ciblé : on rejoue
le prompt de phase complet. La sélection du template est faite par
`PhaseBase[M]` à partir de l'étape 5."""


SCHEMA_RETRY_STRATEGY: RetryStrategy = RetryStrategy.PROGRESSIVE_REASONING
"""Politique appliquée aux erreurs schéma (cf. `SCHEMA_LEVEL_ERRORS`).
Reasoning dès T1 car un LLM qui n'a pas suivi le format au premier coup
bénéficie typiquement d'un modèle plus capable au deuxième."""

SCHEMA_MAX_ATTEMPTS: int = 2
"""Tentatives max sur erreur schéma. Au-delà, le chunk est rejeté."""


RETRY_REGISTRY: dict[ErreursType, RetryEntry[Any, Any]] = {
    ErreursType.LINES_MISSING: RetryEntry(
        template=RetryTemplate.Retry_Missing_Lines_Targeted_Template,
        params_type=MissingLinesParams,
        build=_todo_build,
        mode="merge",
    ),
    ErreursType.FRAGMENT_COUNT_MISMATCH: RetryEntry(
        template=RetryTemplate.Retry_Fragments_Template,
        params_type=RetryFragmentsParams,
        build=_todo_build,
        mode="replace",
    ),
    ErreursType.PUNCTUATION_MISMATCH: RetryEntry(
        template=RetryTemplate.Retry_Punctuation_Template,
        params_type=RetryPunctuationParams,
        build=_todo_build,
        mode="replace",
    ),
    ErreursType.SENTENCE_INVALID: RetryEntry(
        template=RetryTemplate.Retry_Sentence_Template,
        params_type=RetrySentenceParams,
        build=_todo_build,
        mode="merge",
    ),
}
