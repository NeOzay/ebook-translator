"""
Check de validation du nombre de lignes traduites.

Ce check vérifie que toutes les lignes attendues ont été traduites
et corrige automatiquement en retranslant uniquement les lignes manquantes.
"""

import re
from typing import TYPE_CHECKING, cast

from ..logger import get_logger
from .base import Check, CheckResult, ValidationContext, LineCountErrorData, ErrorData

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
        lignes manquantes, les traduit, puis merge avec les traductions
        existantes.

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
        from ..config import TemplateNames
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

        # Construire le contenu source avec seulement les lignes manquantes
        missing_texts = {idx: context.original_texts[idx] for idx in missing_indices}
        source_content = "\n".join(
            f"<{idx}/>{text}" for idx, text in missing_texts.items()
        )

        # Construire prompt ciblé
        prompt = context.llm.render_prompt(
            TemplateNames.Missing_Lines_Targeted_Template,
            target_language=context.target_language,
            missing_indices=missing_indices,
            source_content=source_content,
        )

        logger.debug(
            f"[LineCountCheck] Correction de {len(missing_indices)} lignes "
            f"pour chunk {context.chunk.index}"
        )

        # Appel LLM
        llm_context = f"correction_missing_chunk_{context.chunk.index:03d}"
        llm_output = context.llm.query(prompt, "", context=llm_context)
        corrected_translations = parse_llm_translation_output(llm_output)

        # Valider que le retry a fourni les bons indices
        is_retry_valid, retry_error = validate_retry_indices(
            corrected_translations, missing_indices
        )

        if not is_retry_valid:
            raise ValueError(f"Retry invalide: {retry_error}")

        # Merger avec traductions existantes
        result = dict(context.translated_texts)
        result.update(corrected_translations)

        logger.debug(
            f"[LineCountCheck] Correction réussie: {len(corrected_translations)} lignes corrigées"
        )

        return result
