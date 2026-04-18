"""
Check de validation du nombre de lignes traduites.

Ce check vérifie que toutes les lignes attendues ont été traduites
et corrige automatiquement en retranslant uniquement les lignes manquantes.
"""

import re
from typing import override

from ...logger import get_logger
from .base import (
    CheckResult,
    FailedResult,
    LineCountErrorData,
    SuccessResult,
    ValidationContext,
)
from .intermediate import BatchCheck

logger = get_logger(__name__)


def count_expected_lines(content: str) -> int:
    """
    Compte le nombre de lignes numérotées <N/> dans le contenu source.

    Args:
        content: Contenu source envoyé au LLM (avec balises <N/>)

    Returns:
        Nombre de lignes numérotées trouvées

    Example:
        >>> content = "<0/>Hello\\n<1/>World\\nContext line\\n<2/>!"
        >>> count_expected_lines(content)
        3
    """
    pattern = re.compile(r"^<(\d+)\/>", re.MULTILINE)
    matches = pattern.findall(content)
    return len(matches)


def validate_retry_indices(
    retry_translations: dict[int, str],
    expected_indices: list[int],
) -> tuple[bool, str | None]:
    """
    Valide que le retry a fourni exactement les indices demandés.

    Vérifie que :
    - Tous les indices attendus sont présents dans retry_translations
    - Aucun indice supplémentaire/invalide n'est présent

    Args:
        retry_translations: Dictionnaire {index: texte_traduit} retourné par le retry
        expected_indices: Liste des indices qui devaient être traduits

    Returns:
        Tuple (is_valid, error_message)
        - is_valid: True si les indices correspondent exactement, False sinon
        - error_message: Message d'erreur détaillé si invalide, None sinon

    Example:
        >>> retry_trans = {5: "Hello", 10: "World"}
        >>> expected = [5, 10]
        >>> validate_retry_indices(retry_trans, expected)
        (True, None)

        >>> retry_trans = {5: "Hello", 99: "Invalid"}
        >>> expected = [5, 10]
        >>> validate_retry_indices(retry_trans, expected)
        (False, "❌ Le retry n'a pas fourni les indices corrects...")
    """
    expected_set = set(expected_indices)
    received_set = set(retry_translations.keys())

    missing = expected_set - received_set
    extra = received_set - expected_set

    if not missing and not extra:
        return True, None

    # Construire le message d'erreur
    error_parts = [
        "❌ Le retry n'a pas fourni les indices corrects:",
        f"  • Indices demandés: {sorted(expected_set)[:20]}{'...' if len(expected_set) > 20 else ''}",
        f"  • Indices reçus: {sorted(received_set)[:20]}{'...' if len(received_set) > 20 else ''}",
    ]

    if missing:
        missing_preview = sorted(missing)[:10]
        missing_str = ", ".join(f"<{i}/>" for i in missing_preview)
        if len(missing) > 10:
            missing_str += f" ... (+{len(missing) - 10} autres)"
        error_parts.append(f"  • Toujours manquants: {missing_str}")

    if extra:
        extra_preview = sorted(extra)[:10]
        extra_str = ", ".join(f"<{i}/>" for i in extra_preview)
        if len(extra) > 10:
            extra_str += f" ... (+{len(extra) - 10} autres)"
        error_parts.append(f"  • Indices invalides (non demandés): {extra_str}")

    return False, "\n".join(error_parts)


class LineCountCheck(BatchCheck[LineCountErrorData]):
    """
    Vérifie que toutes les lignes ont été traduites.

    Ce check compare le nombre de traductions reçues avec le nombre
    de lignes originales attendues. En cas de lignes manquantes,
    il retranslate uniquement ces lignes spécifiques via un prompt ciblé.

    Attributes:
        name: Identifiant unique "line_count"

    Example:
        >>> check = LineCountCheck()
        >>> result = check.validate(context)
        >>> if not result.is_valid:
        ...     corrected = check.correct(context, result.error_data)
    """

    @property
    def name(self) -> str:
        """Nom unique du check."""
        return "line_count"

    @override
    def validate(self, context: ValidationContext) -> CheckResult[LineCountErrorData]:
        """
        Valide que toutes les lignes ont été traduites.

        Args:
            context: Contexte de validation

        Returns:
            CheckResult avec is_valid=True si OK, False avec error_data sinon

        Example:
            >>> context = ValidationContext(
            ...     chunk=chunk,
            ...     translated_texts={0: "Bonjour"},  # Manque ligne 1
            ...     original_texts={0: "Hello", 1: "World"},
            ...     ...
            ... )
            >>> result = check.validate(context)
            >>> result.is_valid
            False
            >>> result.error_data["missing_indices"]
            [1]
        """
        expected_count = len(context.original_texts)
        actual_count = len(context.translated_texts)

        if expected_count == actual_count:
            return SuccessResult(check_name=self.name)

        # Trouver les lignes manquantes
        expected_indices = set(context.original_texts.keys())
        actual_indices = set(context.translated_texts.keys())
        missing_indices = sorted(expected_indices - actual_indices)

        error_message = (
            f"Lignes manquantes: {len(missing_indices)}/{expected_count}\n"
            f"  • Indices: {missing_indices[:10]}"
        )
        if len(missing_indices) > 10:
            error_message += f"... (+{len(missing_indices) - 10} autres)"

        return FailedResult(
            check_name=self.name,
            error_message=error_message,
            error_data=LineCountErrorData(
                missing_indices=missing_indices,
                expected_count=expected_count,
                actual_count=actual_count,
            ),
        )

    @override
    def get_invalid_lines(
        self, context: ValidationContext, error_data: LineCountErrorData
    ) -> set[int]:
        """
        Identifie les lignes manquantes comme invalides.

        Args:
            context: Contexte de validation
            error_data: Données d'erreur avec missing_indices

        Returns:
            Set des indices de lignes manquantes (à filtrer)

        Example:
            >>> error_data = {"missing_indices": [5, 10, 15]}
            >>> invalid = check.get_invalid_lines(context, error_data)
            >>> # invalid = {5, 10, 15}
        """
        return set(error_data.missing_indices)

    def build_filter_reason(self, line_idx: int, error_data: LineCountErrorData) -> str:
        return "Ligne manquante après correction"

    # =========================================================================
    # Implémentations des méthodes abstraites de BatchCheck
    # =========================================================================

    @override
    def _render_batch_prompt(
        self,
        context: ValidationContext,
        lines_to_correct: list[int],
        attempt: int,
        use_reasoning: bool,
    ) -> tuple[str, str]:
        if context.llm is None:
            raise ValueError("LLM is None")
        return context.llm.renderer.render_missing_lines(
            context.chunk,
            missing_indices=lines_to_correct,
            target_language=context.target_language,
        )

    @override
    def _validate_batch_output(
        self,
        llm_output: str,
        lines_to_correct: list[int],
        corrected: dict[int, str],
    ) -> bool:
        from ...translation.parser import parse_llm_translation_output

        try:
            parsed = parse_llm_translation_output(llm_output)
            is_valid, retry_error = validate_retry_indices(parsed, lines_to_correct)
            if is_valid:
                corrected.update(parsed)
                return True
            logger.warning(f"[LineCountCheck] Validation échouée: {retry_error}")
            return False
        except Exception as e:
            logger.warning(f"[LineCountCheck] Erreur parsing: {e}")
            return False

    def _get_batch_context_name(self) -> str:
        return "missing_lines"
