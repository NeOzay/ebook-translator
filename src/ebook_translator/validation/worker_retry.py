"""Helpers du worker unifié de validation (Bloc B Step 4a).

Trois primitives consommées par `UnifiedValidationWorker` (Step 4b) :

- `WorkerRetryContext` — implémentation concrète du `RetryContext` Protocol
  consommé par les `build` du `RETRY_REGISTRY`.
- `merge_data` — fusion `prev / new` selon le `mode` de l'entrée registre
  (``replace`` écrase au niveau ligne ; ``merge`` complète sans écraser).
- `lookup_strategy` — résout `(RetryStrategy, max_attempts)` pour une
  `ValidationFailure` : check métadonnées pour les erreurs **contenu**,
  constantes `SCHEMA_*` pour les erreurs **schéma**.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from template.phase.translation_models import LineIndexed

from ..llm.retry_registry import (
    SCHEMA_LEVEL_ERRORS,
    SCHEMA_MAX_ATTEMPTS,
    SCHEMA_RETRY_STRATEGY,
)
from .failure import ValidationFailure
from .retry_strategy import RetryStrategy

if TYPE_CHECKING:
    from ..checks.content_check import ChunkSource, ContentCheck
    from ..segmentation.chunk import ChunkProtocol


@dataclass(frozen=True)
class WorkerRetryContext:
    """Implémentation concrète du `RetryContext` Protocol.

    Frozen pour éviter toute mutation accidentelle entre lookups successifs
    du registre durant la boucle de retry.
    """

    target_language: str
    chunk: ChunkProtocol
    source: ChunkSource
    current_data: dict[int, str]
    max_attempts: int
    attempt: int


def merge_data(
    prev: LineIndexed,
    new: LineIndexed,
    mode: Literal["replace", "merge"],
) -> LineIndexed:
    """Fusionne `prev` et `new` selon le `mode` du `RetryEntry`.

    `replace` : `new` écrase ligne par ligne (correction mono-ligne, ex.
    fragments / ponctuation). `merge` : `new` complète `prev` mais
    n'écrase pas — les lignes déjà valides dans `prev` sont préservées
    (correction batch, ex. lignes manquantes / phrases invalides).

    Note: la sémantique `replace` est ici line-level, non payload-level.
    Le payload accumulatif (toutes les lignes) est conservé ; seules les
    lignes présentes dans `new` sont remplacées.
    """

    if mode == "replace":
        return LineIndexed({**prev, **new})
    # merge : prev a la priorité ; new ne remplit que les trous
    return LineIndexed({**new, **prev})


def is_instance_resolved(
    failure: ValidationFailure[Any],
    current_failures: Sequence[ValidationFailure[Any]],
    mode: Literal["replace", "merge"],
) -> bool:
    """L'instance `failure` est-elle absente de `current_failures` ?

    - `replace` (mono-ligne) : identité = `(error_type, relevant_indices)`.
      `relevant_indices` est un singleton `{line}` pour les checks replace —
      stable, sans dépendance sur une clé ctx.
    - `merge` (batch) : résolue si aucune failure courante du même
      `error_type` partage des indices avec `failure.relevant_indices`.
      Permet de distinguer une correction partielle (indices restants ≠ 0)
      d'une nouvelle failure indépendante sur d'autres indices.
    """

    if mode == "replace":
        return not any(
            f.error_type == failure.error_type
            and f.relevant_indices == failure.relevant_indices
            for f in current_failures
        )

    return not any(
        f.error_type == failure.error_type
        and f.relevant_indices & failure.relevant_indices
        for f in current_failures
    )


def lookup_strategy(
    failure: ValidationFailure[Any],
    content_checks: Sequence[ContentCheck[Any, Any]],
) -> tuple[RetryStrategy, int]:
    """Résout la politique de retry pour une `ValidationFailure`.

    - Erreurs **schéma** (`SCHEMA_LEVEL_ERRORS`) : retournent les
      constantes globales `SCHEMA_RETRY_STRATEGY` /
      `SCHEMA_MAX_ATTEMPTS`. Le check ne porte pas l'erreur (Pydantic).
    - Erreurs **contenu** : on cherche dans `content_checks` le check
      dont `error_type` matche celui de la failure. La politique vient
      des `ClassVar` du check.

    Raises:
        KeyError: Si aucune entrée ne peut être résolue (invariant
            registre cassé : ajouter le check à la phase, ou inscrire
            l'`error_type` dans `SCHEMA_LEVEL_ERRORS`).
    """

    if failure.error_type in SCHEMA_LEVEL_ERRORS:
        return SCHEMA_RETRY_STRATEGY, SCHEMA_MAX_ATTEMPTS

    for check in content_checks:
        if check.error_type == failure.error_type:
            return check.retry_strategy, check.max_attempts

    raise KeyError(
        f"Aucune politique trouvée pour error_type={failure.error_type!r}. "
        "Ajouter le check correspondant à la phase, ou inscrire l'erreur "
        "dans SCHEMA_LEVEL_ERRORS si elle est de niveau schéma."
    )
