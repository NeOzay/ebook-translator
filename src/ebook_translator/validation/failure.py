"""Erreur de validation typée commune au pipeline.

`ValidationFailure[CtxT]` unifie les erreurs Pydantic (schéma) et les erreurs
des `ContentCheck` externes derrière un seul type. Le champ `error_type`
est une valeur de `ErreursType` qui permet de retrouver le template et le
constructeur de paramètres associés via `RETRY_REGISTRY`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, ValidationError

if TYPE_CHECKING:
    from ebook_translator.checks.content_check import ContentCheck

    # Typage statique fort côté basedpyright.
    type CheckSource = type[ContentCheck[Any, Any]]
else:
    # `ContentCheck` est un Protocol non runtime_checkable : Pydantic ne peut
    # pas faire `issubclass` dessus. On lui donne `type` nu au runtime. Cet
    # import est aussi celui qui fermerait le cycle checks ↔ validation.
    CheckSource = type

from .diagnostics import (
    DuplicateIndicesDiagnostic,
    ErreursType,
    FragmentDiagnostic,
    LinesMissingDiagnostic,
    MissingEndMarkerDiagnostic,
    OutputFormatDiagnostic,
    PunctuationDiagnostic,
    SentenceDiagnostic,
)


class ValidationFailure[CtxT: Mapping[str, Any]](BaseModel):
    """Erreur de validation, indépendante de son origine (Pydantic ou check).

    Args:
        error_type: Code stable utilisé pour router vers une entrée
            `RETRY_REGISTRY`. Doit correspondre à un `PydanticCustomError.type`
            ou à `ContentCheck.error_type`.
        msg: Message lisible pour les logs.
        ctx: Diagnostic typé (voir `validation.diagnostics`). Contient
            uniquement ce que le check produit, sans fuite d'environnement
            (pas de `target_language`, `source_text`, etc.).
        loc: Localisation Pydantic (vide pour les checks externes).
    """

    model_config = ConfigDict(frozen=True)

    error_type: ErreursType
    # `None` pour les erreurs de schéma Pydantic : elles ne proviennent
    # d'aucun `ContentCheck` (cf. `from_pydantic_error`).
    check_source: CheckSource | None = None
    msg: str
    ctx: CtxT
    loc: tuple[str | int, ...] = ()
    relevant_indices: frozenset[int]
    attempt: int = 0


def from_pydantic_error(
    exc: ValidationError,
) -> list[ValidationFailure[Mapping[str, Any]]]:
    """Convertit une `ValidationError` Pydantic en liste de `ValidationFailure`.

    Préserve l'ordre des erreurs renvoyé par Pydantic. Les `ctx` non typés
    sont remontés tels quels comme `Mapping[str, Any]`; le typage fort est
    réintroduit côté consommateur via `DIAGNOSTIC_BY_TYPE`.

    Raises:
        ValueError: Si un `error_type` inconnu de `ErreursType` apparaît.
            Garantit l'invariant « tout error_type émis a une entrée registre ».
    """

    failures: list[ValidationFailure[Mapping[str, Any]]] = []
    for err in exc.errors():
        try:
            error_type = ErreursType(err["type"])
        except ValueError as e:
            raise ValueError(
                f"error_type {err['type']!r} non couvert par ErreursType. "
                "Ajouter une entrée dans ErreursType, DIAGNOSTIC_BY_TYPE et "
                "RETRY_REGISTRY."
            ) from e
        ctx_raw = err.get("ctx")
        ctx: Mapping[str, Any] = ctx_raw if isinstance(ctx_raw, Mapping) else {}
        failures.append(
            ValidationFailure[Mapping[str, Any]](
                error_type=error_type,
                msg=err["msg"],
                ctx=ctx,
                loc=tuple(err["loc"]),
                relevant_indices=frozenset(),
            )
        )
    return failures


type Failure = (
    ValidationFailure[OutputFormatDiagnostic]
    | ValidationFailure[MissingEndMarkerDiagnostic]
    | ValidationFailure[DuplicateIndicesDiagnostic]
    | ValidationFailure[LinesMissingDiagnostic]
    | ValidationFailure[FragmentDiagnostic]
    | ValidationFailure[PunctuationDiagnostic]
    | ValidationFailure[SentenceDiagnostic]
)
