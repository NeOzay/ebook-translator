"""
Check de validation du nombre de lignes traduites.

Ce check vérifie que toutes les lignes attendues ont été traduites
et corrige automatiquement en retranslant uniquement les lignes manquantes.
"""

import re
from typing import TYPE_CHECKING, cast

from ..logger import get_logger
from .base import Check, CheckResult, ValidationContext, LineCountErrorData, ErrorData
from .retry_helper import retry_with_reasoning

if TYPE_CHECKING:
    pass

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


class LineCountCheck(Check):
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

    def validate(self, context: ValidationContext) -> CheckResult:
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
            return CheckResult(is_valid=True, check_name=self.name)

        # Trouver les lignes manquantes
        expected_indices = set(context.original_texts.keys())
        actual_indices = set(context.translated_texts.keys())
        missing_indices = sorted(expected_indices - actual_indices)

        error_message = (
            f"Lignes manquantes: {len(missing_indices)}/{expected_count}\n"
            f"  • Indices: {missing_indices[:10]}"
            + (
                f"... (+{len(missing_indices) - 10} autres)"
                if len(missing_indices) > 10
                else ""
            )
        )

        error_data: LineCountErrorData = {
            "missing_indices": missing_indices,
            "expected_count": expected_count,
            "actual_count": actual_count,
        }

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
        Corrige en retranslant uniquement les lignes manquantes.

        Cette méthode construit un prompt ciblé contenant seulement les
        lignes manquantes, les traduit avec retry automatique (normal → reasoning),
        puis merge avec les traductions existantes.

        Args:
            context: Contexte de validation
            error_data: Données d'erreur avec missing_indices, expected_count, actual_count

        Returns:
            Nouvelles traductions {line_index: translated_text} incluant corrections

        Raises:
            Exception: Si context.llm est None ou traduction échoue

        Example:
            >>> # Contexte avec ligne 1 manquante
            >>> error_data = {"missing_indices": [1]}
            >>> corrected = check.correct(context, error_data)
            >>> # corrected = {0: "Bonjour", 1: "Monde"}
        """
        from ..translation.parser import (
            parse_llm_translation_output,
            validate_retry_indices,
        )

        if context.llm is None:
            raise ValueError(
                "Correction impossible: context.llm est None (mode lecture seule)"
            )

        # Type narrowing: on sait que error_data est LineCountErrorData
        typed_error_data = cast(LineCountErrorData, error_data)
        missing_indices = typed_error_data["missing_indices"]

        logger.info(
            f"[LineCountCheck] Correction de {len(missing_indices)} lignes "
            f"pour chunk {context.chunk.index}"
        )

        # Stocker les corrections réussies
        corrected_translations: dict[int, str] = {}

        # Fonction de rendu du prompt
        def render_prompt(attempt: int, use_reasoning: bool) -> str:
            # Le paramètre use_reasoning est passé mais non utilisé ici
            # car le même template est utilisé pour les deux tentatives
            if context.llm is None:
                raise ValueError("LLM is None")
            return context.llm.renderer.render_missing_lines(
                context.chunk,
                missing_indices=missing_indices,
                target_language=context.target_language,
            )

        # Fonction de validation
        def validate_result(llm_output: str) -> bool:
            try:
                parsed = parse_llm_translation_output(llm_output)

                # Valider que le retry a fourni les bons indices
                is_retry_valid, retry_error = validate_retry_indices(
                    parsed, missing_indices
                )

                if is_retry_valid:
                    # Stocker les corrections pour utilisation après
                    corrected_translations.update(parsed)
                    return True
                else:
                    logger.warning(
                        f"[LineCountCheck] Validation échouée: {retry_error}"
                    )
                    return False
            except Exception as e:
                logger.warning(f"[LineCountCheck] Erreur parsing: {e}")
                return False

        # Exécuter le retry avec reasoning
        success, _ = retry_with_reasoning(
            context=context,
            render_prompt=render_prompt,
            validate_result=validate_result,
            context_name="missing_lines",
            max_attempts=2,
        )

        if not success:
            raise ValueError(
                f"[LineCountCheck] Échec correction après 2 tentatives pour chunk {context.chunk.index}"
            )

        # Merger avec traductions existantes
        result = dict(context.translated_texts)
        result.update(corrected_translations)

        logger.info(
            f"[LineCountCheck] ✅ Correction réussie: {len(corrected_translations)} lignes corrigées"
        )

        return result

    def get_invalid_lines(
        self, context: ValidationContext, error_data: ErrorData
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
        typed_error_data = cast(LineCountErrorData, error_data)
        return set(typed_error_data["missing_indices"])

    def build_filter_reason(self, line_idx, error_data):
        return "Ligne manquante après correction"
