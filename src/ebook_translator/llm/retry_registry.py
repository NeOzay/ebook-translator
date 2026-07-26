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

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from template.template_params import (
    MissingLinesParams,
    RetryFragmentsParams,
    RetryPunctuationParams,
    RetrySentenceParams,
)

from ..validation.diagnostics import (
    ErreursType,
    FragmentDiagnostic,
    LinesMissingDiagnostic,
    PunctuationDiagnostic,
    SentenceDiagnostic,
)
from ..validation.failure import ValidationFailure
from ..validation.retry_context import RetryContext
from ..validation.retry_strategy import RetryStrategy
from .template_renderers import RetryTemplate


@dataclass(frozen=True)
class RetryEntry[D: Mapping[str, object], P: Mapping[str, object]]:
    """Décrit comment retraiter une `ValidationFailure` donnée.

    Attributes:
        template: Membre `RetryTemplate` qui résout la paire system/user.
        params_type: `TypedDict` des paramètres attendus par le template.
            Le retour de `build` doit être assignable à ce type.
        build: Fonction qui combine le diagnostic typé et le `RetryContext`
            (target_language, chunk, source, current_data) pour produire
            un `params_type` complet.
        mode: Sémantique de fusion entre la dernière sortie partielle et la
            réponse du retry. `replace` écrase entièrement la ligne (mono-
            ligne : fragment, punctuation), `merge` fusionne au niveau du
            payload (batch : lignes manquantes, phrases invalides).
    """

    template: RetryTemplate
    params_type: type[P]
    build: Callable[[ValidationFailure[D], RetryContext], P]
    mode: Literal["replace", "merge"]


def _build_missing_lines(
    failure: ValidationFailure[LinesMissingDiagnostic], context: RetryContext
) -> MissingLinesParams:
    missing = failure.ctx["missing_indices"]
    source_content = context.chunk.prepare_for_prompt(missing)
    preview = ", ".join(f"<{idx}/>" for idx in missing[:5])
    if len(missing) > 5:
        preview += f" ... (+{len(missing) - 5} autres)"
    return {
        "target_language": context.target_language,
        "missing_indices": missing,
        "source_content": source_content,
        "error_message": (
            f"Tu as oublié {len(missing)} ligne(s) numérotée(s) : {preview}"
        ),
    }


def _build_fragments(
    failure: ValidationFailure[FragmentDiagnostic], context: RetryContext
) -> RetryFragmentsParams:
    line = failure.ctx["line"]
    max_attempts = context.max_attempts
    attempt = context.attempt
    return {
        "target_language": context.target_language,
        "original_text": context.source.text_at(line),
        "incorrect_translation": context.current_data[line],
        "expected_separators": failure.ctx["expected_pairs"],
        "actual_separators": failure.ctx["actual_pairs"],
        # `mode` est porté par la `RetryStrategy` du check côté worker
        # (PROGRESSIVE_REASONING bascule strict→flexible à T2). Par défaut
        # strict ; le worker peut surcharger via un wrapper si besoin.
        "mode": "strict" if attempt < max_attempts - 1 else "flexible",
    }


def _build_punctuation(
    failure: ValidationFailure[PunctuationDiagnostic], context: RetryContext
) -> RetryPunctuationParams:
    line = failure.ctx["line"]
    return {
        "target_language": context.target_language,
        "original_text": context.source.text_at(line),
        "incorrect_translation": context.current_data[line],
        "expected_pairs": failure.ctx["expected_pairs"],
        "actual_pairs": failure.ctx["actual_pairs"],
    }


def _build_sentence(
    failure: ValidationFailure[SentenceDiagnostic], context: RetryContext
) -> RetrySentenceParams:
    invalid = failure.ctx["invalid_indices"]
    original_text = context.chunk.prepare_for_prompt(invalid)
    previous_translation = "\n".join(
        f"<{i}/>{context.current_data[i]}" for i in invalid if i in context.current_data
    )
    return {
        "target_language": context.target_language,
        "original_text": original_text,
        "previous_translation": previous_translation,
        "missing_indices": ", ".join(f"<{i}/>" for i in invalid),
    }


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
        build=_build_missing_lines,
        mode="merge",
    ),
    ErreursType.FRAGMENT_COUNT_MISMATCH: RetryEntry(
        template=RetryTemplate.Retry_Fragments_Template,
        params_type=RetryFragmentsParams,
        build=_build_fragments,
        mode="replace",
    ),
    ErreursType.PUNCTUATION_MISMATCH: RetryEntry(
        template=RetryTemplate.Retry_Punctuation_Template,
        params_type=RetryPunctuationParams,
        build=_build_punctuation,
        mode="replace",
    ),
    ErreursType.SENTENCE_INVALID: RetryEntry(
        template=RetryTemplate.Retry_Sentence_Template,
        params_type=RetrySentenceParams,
        build=_build_sentence,
        mode="merge",
    ),
}
