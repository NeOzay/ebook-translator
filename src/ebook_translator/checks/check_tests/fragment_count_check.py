"""
Check de validation du nombre de fragments.

Ce check vérifie que le nombre de séparateurs </> correspond entre
texte original et traduit, et corrige automatiquement en retranslant
les lignes problématiques avec un prompt strict.
"""

from typing import override

from ...constants import FRAGMENT_SEPARATOR
from ...logger import get_logger
from .base import (
    CheckResult,
    FailedResult,
    FragmentCountErrorData,
    FragmentErrorDetail,
    SuccessResult,
    ValidationContext,
)
from .intermediate import PerLineCheck

logger = get_logger(__name__)


class FragmentCountCheck(PerLineCheck[FragmentCountErrorData, FragmentErrorDetail]):
    """
        Vérifie que le nombre de fragments </> correspond.

        Ce check compare le nombre de séparateurs </> dans chaque ligne
        traduite avec le nombre attendu dans le texte original. Les fragments
        sont utilisés lors de la reconstruction HTML pour aligner correctement
        les traductions avec les balises.

        En cas d'erreur, retranslate les lignes problématiques individuellement
        avec un prompt ultra-strict insistant sur la préservation des séparateurs.

        Attributes:
            name: Identifiant unique "fragment_count"

        Example:
            >>> check = FragmentCountCheck()
    /usr/bin/bash: ligne 1: qa: commande introuvable
            >>> if not result.is_valid:
            ...     corrected = check.correct(context, result.error_data)
    """

    @property
    @override
    def name(self) -> str:
        """Nom unique du check."""
        return "fragment_count"

    @override
    def validate(
        self, context: ValidationContext
    ) -> CheckResult[FragmentCountErrorData]:
        """
        Valide que le nombre de fragments correspond pour chaque ligne.

        Args:
            context: Contexte de validation

        Returns:
            CheckResult avec is_valid=True si OK, False avec error_data sinon

        Example:
            >>> context = ValidationContext(
            ...     chunk=chunk,
            ...     translated_texts={0: "Bonjour monde"},  # Séparateur manquant
            ...     original_texts={0: "Hello</>world"},    # Contient </>
            ...     ...
            ... )
            >>> result = check.validate(context)
            >>> result.is_valid
            False
            >>> result.error_data["errors"][0]
            {
                "line_idx": 0,
                "original_text": "Hello</>world",
                "translated_text": "Bonjour monde",
                "expected_fragments": 2,
                "actual_fragments": 1,
            }
        """
        errors: list[FragmentErrorDetail] = []

        # Vérifier chaque paire (original, traduit)
        for line_idx, translated_text in context.translated_texts.items():
            if line_idx not in context.original_texts:
                # Ligne traduite sans original (ne devrait pas arriver)
                continue

            original_text = context.original_texts[line_idx]
            # Compter les séparateurs (pas les segments)
            expected_separators = original_text.count(FRAGMENT_SEPARATOR)
            actual_separators = translated_text.count(FRAGMENT_SEPARATOR)

            if expected_separators != actual_separators:
                # expected_fragments = nombre de segments (séparateurs + 1)
                error_detail: FragmentErrorDetail = {
                    "line_idx": line_idx,
                    "original_text": original_text,
                    "translated_text": translated_text,
                    "expected_fragments": expected_separators + 1,
                    "actual_fragments": actual_separators + 1,
                }
                errors.append(error_detail)

        if not errors:
            return SuccessResult(check_name=self.name)

        # Construire message d'erreur
        first_error = errors[0]
        expected_sep = first_error["expected_fragments"] - 1
        actual_sep = first_error["actual_fragments"] - 1
        text_type = "Texte continu" if expected_sep == 0 else "Texte fragmenté"

        error_message = (
            f"Nombre de séparateurs </> incorrect sur {len(errors)} ligne(s)\n"
            f"  • Première erreur: ligne {first_error['line_idx']}\n"
            f"    - Séparateurs attendus: {expected_sep}\n"
            f"    - Séparateurs reçus: {actual_sep}\n"
            f"    - Type: {text_type}"
        )

        return FailedResult(
            check_name=self.name,
            error_message=error_message,
            error_data=FragmentCountErrorData(errors=errors),
        )

    @override
    def build_filter_reason(
        self, line_idx: int, error_data: FragmentCountErrorData
    ) -> str:
        # Chercher détails dans error_data
        for err in error_data.errors:
            if err.get("line_idx") == line_idx:
                expected = err.get("expected_fragments", "?")
                actual = err.get("actual_fragments", "?")
                return f"Fragments: attendu {expected}, reçu {actual}"
        return "Nombre de fragments incorrect"

    # =========================================================================
    # Implémentations des méthodes abstraites de PerLineCheck
    # =========================================================================

    @override
    def _get_errors(
        self, error_data: FragmentCountErrorData
    ) -> list[FragmentErrorDetail]:
        return error_data.errors

    @override
    def _render_line_prompt(
        self,
        context: ValidationContext,
        error: FragmentErrorDetail,
        attempt: int,
        use_reasoning: bool,
    ) -> tuple[str, str]:
        if context.llm is None:
            raise ValueError("LLM is None")
        expected_separators = error["expected_fragments"] - 1
        actual_separators = error["actual_fragments"] - 1
        return context.llm.renderer.render_retry_fragments(
            target_language=context.target_language,
            original_text=error["original_text"],
            incorrect_translation=error["translated_text"],
            expected_separators=expected_separators,
            actual_separators=actual_separators,
            mode="flexible" if attempt >= 2 or use_reasoning else "strict",
        )

    @override
    def _validate_line_output(
        self,
        llm_output: str,
        error: FragmentErrorDetail,
        result: dict[int, str],
    ) -> bool:
        from ...translation.parser import parse_llm_translation_output

        try:
            corrected_line = parse_llm_translation_output("<0/>" + llm_output)
            if 0 not in corrected_line:
                return False
            corrected_text = corrected_line[0]
            expected_separators = error["expected_fragments"] - 1
            if corrected_text.count(FRAGMENT_SEPARATOR) == expected_separators:
                result[error["line_idx"]] = corrected_text
                return True
            return False
        except Exception:
            return False

    @override
    def _get_context_name(
        self, error: FragmentErrorDetail, context: ValidationContext
    ) -> str:
        return f"fragment_line_{error['line_idx']}"

    @override
    def _get_max_attempts(self) -> int:
        return 3
