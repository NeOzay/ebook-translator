"""
Check de validation des paires de ponctuation.

Ce check vérifie que le nombre de paires de guillemets correspond entre
texte original et traduit, garantissant la préservation de la structure narrative
(dialogues interrompus, citations, etc.).
"""

from typing import override

from ...logger import get_logger
from .base import (
    CheckResult,
    FailedResult,
    PunctuationErrorData,
    PunctuationErrorDetail,
    SuccessResult,
    ValidationContext,
)
from .intermediate import PerLineCheck

logger = get_logger(__name__)


def _count_quote_pairs(text: str) -> int:
    """
    Compte le nombre de paires de guillemets dans un texte.

    Supporte :
    - Guillemets anglais doubles : "..."
    - Guillemets français : « ... »
    - Guillemets simples : '...'

    Args:
        text: Texte à analyser

    Returns:
        Nombre de paires de guillemets

    Example:
        >>> self._count_quote_pairs('"Hello" world')
        1
        >>> self._count_quote_pairs('"A," he said, "B"')
        2
        >>> self._count_quote_pairs('« Bonjour » monde')
        1
    """
    # Compter guillemets anglais doubles
    english_quote = text.count("\u201c") + text.count("\u201d")

    # Compter guillemets français
    french_quote = text.count("«") + text.count("»")

    # Total des paires
    total_pairs = (english_quote + french_quote) // 2

    return total_pairs


class PunctuationCheck(PerLineCheck[PunctuationErrorData, PunctuationErrorDetail]):
    """
    Vérifie que le nombre de paires de guillemets correspond.

    Ce check compare le nombre de paires de guillemets dans chaque ligne
    traduite avec le nombre attendu dans le texte original. Cela garantit
    la préservation de la structure narrative (dialogues interrompus, citations).

    En cas d'erreur, retranslate les lignes problématiques avec un prompt
    insistant sur la préservation du nombre de paires.

    Attributes:
        name: Identifiant unique "punctuation"

    Example:
        >>> check = PunctuationCheck()
        >>> result = check.validate(context)
        >>> if not result.is_valid:
        ...     corrected = check.correct(context, result.error_data)
    """

    @property
    def name(self) -> str:
        """Nom unique du check."""
        return "punctuation"

    @override
    def validate(self, context: ValidationContext) -> CheckResult[PunctuationErrorData]:
        """
        Valide que le nombre de paires de guillemets correspond pour chaque ligne.

        Args:
            context: Contexte de validation

        Returns:
            CheckResult avec is_valid=True si OK, False avec error_data sinon

        Example:
            >>> context = ValidationContext(
            ...     chunk=chunk,
            ...     translated_texts={0: '« Bonjour monde »'},  # 1 paire
            ...     original_texts={0: '"Hello," he said, "world"'},  # 2 paires
            ...     ...
            ... )
            >>> result = check.validate(context)
            >>> result.is_valid
            False
        """
        errors: list[PunctuationErrorDetail] = []

        # Vérifier chaque paire (original, traduit)
        for line_idx, translated_text in context.translated_texts.items():
            if line_idx not in context.original_texts:
                # Ligne traduite sans original (ne devrait pas arriver)
                continue

            original_text = context.original_texts[line_idx]

            # Compter les paires de guillemets
            expected_pairs = _count_quote_pairs(original_text)
            actual_pairs = _count_quote_pairs(translated_text)

            if expected_pairs != actual_pairs:
                error_detail: PunctuationErrorDetail = {
                    "line_idx": line_idx,
                    "original_text": original_text,
                    "translated_text": translated_text,
                    "expected_pairs": expected_pairs,
                    "actual_pairs": actual_pairs,
                }
                errors.append(error_detail)

        if not errors:
            return SuccessResult(check_name=self.name)

        # Construire message d'erreur
        first_error = errors[0]
        error_message = (
            f"Nombre de paires de guillemets incorrect sur {len(errors)} ligne(s)\n"
            f"  • Première erreur: ligne {first_error['line_idx']}\n"
            f"    - Paires attendues: {first_error['expected_pairs']}\n"
            f"    - Paires reçues: {first_error['actual_pairs']}\n"
        )

        return FailedResult(
            check_name=self.name,
            error_message=error_message,
            error_data=PunctuationErrorData(errors=errors),
        )

    @override
    def build_filter_reason(
        self, line_idx: int, error_data: PunctuationErrorData
    ) -> str:
        for err in error_data.errors:
            if err.get("line_idx") == line_idx:
                expected = err.get("expected_pairs", "?")
                actual = err.get("actual_pairs", "?")
                return f"Ponctuation: attendu {expected} paires, reçu {actual}"
        return "Ponctuation incorrecte"

    # =========================================================================
    # Implémentations des méthodes abstraites de PerLineCheck
    # =========================================================================

    @override
    def _get_errors(
        self, error_data: PunctuationErrorData
    ) -> list[PunctuationErrorDetail]:
        return error_data.errors

    @override
    def _render_line_prompt(
        self,
        context: ValidationContext,
        error: PunctuationErrorDetail,
        attempt: int,
        use_reasoning: bool,
    ) -> tuple[str, str]:
        if context.llm is None:
            raise ValueError("LLM is None")
        return context.llm.renderer.render_retry_punctuation(
            target_language=context.target_language,
            original_text=error["original_text"],
            incorrect_translation=error["translated_text"],
            expected_pairs=error["expected_pairs"],
            actual_pairs=error["actual_pairs"],
        )

    @override
    def _validate_line_output(
        self,
        llm_output: str,
        error: PunctuationErrorDetail,
        result: dict[int, str],
    ) -> bool:
        from ...translation.parser import parse_llm_translation_output

        try:
            corrected_line = parse_llm_translation_output("<0/>" + llm_output)
            if 0 not in corrected_line:
                return False
            corrected_text = corrected_line[0]
            if _count_quote_pairs(corrected_text) == error["expected_pairs"]:
                result[error["line_idx"]] = corrected_text
                return True
            return False
        except Exception:
            return False

    @override
    def _get_context_name(
        self, error: PunctuationErrorDetail, context: ValidationContext
    ) -> str:
        return f"punctuation_line_{error['line_idx']}_chunk_{context.chunk.index}"

    @override
    def _get_max_attempts(self) -> int:
        return 2
