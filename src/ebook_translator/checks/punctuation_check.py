"""
Check de validation des paires de ponctuation.

Ce check vérifie que le nombre de paires de guillemets correspond entre
texte original et traduit, garantissant la préservation de la structure narrative
(dialogues interrompus, citations, etc.).
"""

from typing import TYPE_CHECKING, cast

from ..logger import get_logger
from .base import (
    Check,
    CheckResult,
    PunctuationErrorData,
    PunctuationErrorDetail,
    ValidationContext,
    ErrorData,
)
from .retry_helper import retry_with_reasoning

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class PunctuationCheck(Check):
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

    def _count_quote_pairs(self, text: str) -> int:
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
        # double_quotes = text.count('"')
        english_quote = text.count("“") + text.count("”")

        # Compter guillemets français
        french_quote = text.count("«") + text.count("»")

        # Compter guillemets simples
        # single_quotes = text.count("'")
        # pairs_single = single_quotes // 2

        # Total des paires
        total_pairs = (english_quote + french_quote) // 2

        return total_pairs

    def validate(self, context: ValidationContext) -> CheckResult:
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
            >>> result.error_data["errors"][0]
            {
                "line_idx": 0,
                "original_text": '"Hello," he said, "world"',
                "translated_text": '« Bonjour monde »',
                "expected_pairs": 2,
                "actual_pairs": 1,
            }
        """
        errors = []

        # Vérifier chaque paire (original, traduit)
        for line_idx, translated_text in context.translated_texts.items():
            if line_idx not in context.original_texts:
                # Ligne traduite sans original (ne devrait pas arriver)
                continue

            original_text = context.original_texts[line_idx]

            # Compter les paires de guillemets
            expected_pairs = self._count_quote_pairs(original_text)
            actual_pairs = self._count_quote_pairs(translated_text)

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
            return CheckResult(is_valid=True, check_name=self.name)

        # Construire message d'erreur
        first_error = errors[0]
        expected_p = first_error["expected_pairs"]
        actual_p = first_error["actual_pairs"]

        error_message = (
            f"Nombre de paires de guillemets incorrect sur {len(errors)} ligne(s)\n"
            f"  • Première erreur: ligne {first_error['line_idx']}\n"
            f"    - Paires attendues: {expected_p}\n"
            f"    - Paires reçues: {actual_p}\n"
        )

        error_data: PunctuationErrorData = {"errors": errors}

        return CheckResult(
            is_valid=False,
            check_name=self.name,
            error_message=error_message,
            error_data=error_data,
        )

    def correct(
        self, context: ValidationContext, error_data: ErrorData
    ) -> dict[int, str]:
        """
        Corrige en retranslant les lignes avec mauvais nombre de paires.

        Cette méthode retraduit chaque ligne problématique individuellement
        avec un prompt strict insistant sur la préservation du nombre de paires.

        Args:
            context: Contexte de validation
            error_data: Données d'erreur avec liste d'erreurs de ponctuation

        Returns:
            Nouvelles traductions {line_index: translated_text} incluant corrections

        Raises:
            Exception: Si context.llm est None ou traduction échoue

        Example:
            >>> error_data = {
            ...     "errors": [{
            ...         "line_idx": 0,
            ...         "original_text": '"A," he said, "B"',
            ...         "expected_pairs": 2,
            ...     }]
            ... }
            >>> corrected = check.correct(context, error_data)
            >>> # corrected[0] contiendra maintenant 2 paires de guillemets
        """
        from ..translation.parser import parse_llm_translation_output

        if context.llm is None:
            raise ValueError(
                "Correction impossible: context.llm est None (mode lecture seule)"
            )

        # Type narrowing
        typed_error_data = cast(PunctuationErrorData, error_data)
        errors = typed_error_data["errors"]
        result = dict(context.translated_texts)

        logger.info(
            f"[PunctuationCheck] Correction de {len(errors)} ligne(s) "
            f"pour chunk {context.chunk.index} (max {context.max_retries} tentatives)"
        )

        # Retranslater chaque ligne problématique
        for error in errors:
            line_idx = error["line_idx"]
            original_text = error["original_text"]
            expected_pairs = error["expected_pairs"]
            actual_pairs = error["actual_pairs"]
            incorrect_translation = error["translated_text"]

            # Fonction de rendu du prompt
            def render_prompt(attempt: int, use_reasoning: bool) -> str:
                # Le paramètre use_reasoning est passé mais non utilisé ici
                # car le même template est utilisé pour les deux tentatives
                if context.llm is None:
                    raise ValueError("LLM is None")
                return context.llm.renderer.render_retry_punctuation(
                    target_language=context.target_language,
                    original_text=original_text,
                    incorrect_translation=incorrect_translation,
                    expected_pairs=expected_pairs,
                    actual_pairs=actual_pairs,
                )

            # Fonction de validation
            def validate_result(llm_output: str) -> bool:
                try:
                    corrected_line = parse_llm_translation_output("<0/>" + llm_output)
                    if 0 not in corrected_line:
                        return False
                    corrected_text = corrected_line[0]
                    corrected_pairs = self._count_quote_pairs(corrected_text)

                    # Validation : NOMBRE EXACT requis
                    if corrected_pairs == expected_pairs:
                        # Stocker le résultat pour l'utiliser après
                        result[line_idx] = corrected_text
                        return True
                    return False
                except Exception:
                    return False

            # Exécuter le retry avec reasoning
            success, _ = retry_with_reasoning(
                context=context,
                render_prompt=render_prompt,
                validate_result=validate_result,
                context_name=f"punctuation_line_{line_idx}",
                max_attempts=2,
            )

            if not success:
                logger.error(
                    f"[PunctuationCheck] ❌ Échec correction chunk {context.chunk.index}, "
                    f"ligne {line_idx} après 2 tentatives"
                )

        return result

    def get_invalid_lines(
        self, context: ValidationContext, error_data: ErrorData
    ) -> set[int]:
        """
        Identifie les lignes avec mauvaise ponctuation comme invalides.

        Args:
            context: Contexte de validation
            error_data: Données d'erreur avec liste d'erreurs de ponctuation

        Returns:
            Set des indices de lignes avec ponctuation incorrecte (à filtrer)

        Example:
            >>> error_data = {
            ...     "errors": [
            ...         {"line_idx": 3, ...},
            ...         {"line_idx": 7, ...},
            ...     ]
            ... }
            >>> invalid = check.get_invalid_lines(context, error_data)
            >>> # invalid = {3, 7}
        """
        typed_error_data = cast(PunctuationErrorData, error_data)
        return {error["line_idx"] for error in typed_error_data["errors"]}

    def build_filter_reason(self, line_idx, error_data: PunctuationErrorData):
        for err in error_data["errors"]:
            if err.get("line_idx") == line_idx:
                expected = err.get("expected_pairs", "?")
                actual = err.get("actual_pairs", "?")
                return f"Ponctuation: attendu {expected} paires, reçu {actual}"
        return "Ponctuation incorrecte"
