"""
Classes abstraites intermédiaires pour réduire la redondance entre checks.

Ce module définit deux templates de correction :
- `PerLineCheck` : correction ligne-par-ligne (fragment, ponctuation)
- `BatchCheck` : correction en batch d'un groupe de lignes (line_count, sentence)
"""

from abc import abstractmethod
from typing import TYPE_CHECKING, override

from ...logger import get_logger
from ..retry_helper import retry_with_reasoning
from .base import Check, ErrorData, HasLineIdx, ValidationContext

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class PerLineCheck[E: ErrorData, D: HasLineIdx](Check[E]):
    """
    Check abstrait pour correction ligne-par-ligne.

    Fournit des implémentations concrètes de `correct()` et `get_invalid_lines()`
    en déléguant uniquement la logique métier spécifique à chaque check via les
    méthodes abstraites `_render_line_prompt` et `_validate_line_output`.

    Type parameters:
        E: Type ErrorData complet (ex: FragmentCountErrorData)
        D: Type du détail d'erreur portant line_idx (ex: FragmentErrorDetail)
    """

    @abstractmethod
    def _get_errors(self, error_data: E) -> list[D]:
        """Extrait la liste des détails d'erreur depuis error_data."""
        ...

    @abstractmethod
    def _render_line_prompt(
        self,
        context: ValidationContext,
        error: D,
        attempt: int,
        use_reasoning: bool,
    ) -> tuple[str, str]:
        """Génère le prompt pour corriger une ligne spécifique."""
        ...

    @abstractmethod
    def _validate_line_output(
        self,
        llm_output: str,
        error: D,
        result: dict[int, str],
    ) -> bool:
        """
        Valide la sortie LLM pour une ligne et met à jour result si valide.

        Args:
            llm_output: Sortie brute du LLM
            error: Détail de l'erreur pour cette ligne
            result: Dict de traductions à mettre à jour si la correction est valide

        Returns:
            True si la correction est valide et result a été mis à jour
        """
        ...

    @abstractmethod
    def _get_context_name(self, error: D, context: ValidationContext) -> str:
        """Retourne le nom de contexte pour les logs de retry."""
        ...

    @abstractmethod
    def _get_max_attempts(self) -> int:
        """Retourne le nombre maximum de tentatives de correction."""
        ...

    @override
    def correct(self, context: ValidationContext, error_data: E) -> dict[int, str]:
        """Corrige chaque ligne problématique individuellement via retry."""
        if context.llm is None:
            raise ValueError(
                "Correction impossible: context.llm est None (mode lecture seule)"
            )
        errors = self._get_errors(error_data)
        result = dict(context.translated_texts)

        logger.info(
            f"[{type(self).__name__}] Correction de {len(errors)} ligne(s) "
            f"pour chunk {context.chunk.index} (max {self._get_max_attempts()} tentatives)"
        )

        for error in errors:
            line_idx = error["line_idx"]

            def render_prompt(
                attempt: int,
                use_reasoning: bool,
                _error: D = error,
            ) -> tuple[str, str]:
                return self._render_line_prompt(context, _error, attempt, use_reasoning)

            def validate_result(
                llm_output: str,
                _error: D = error,
            ) -> bool:
                return self._validate_line_output(llm_output, _error, result)

            success, _ = retry_with_reasoning(
                context=context,
                render_prompt=render_prompt,
                validate_result=validate_result,
                context_name=self._get_context_name(error, context),
                max_attempts=self._get_max_attempts(),
            )

            if not success:
                logger.error(
                    f"[{type(self).__name__}] ❌ Échec correction chunk "
                    f"{context.chunk.index}, ligne {line_idx} après "
                    f"{self._get_max_attempts()} tentatives"
                )

        return result

    @override
    def get_invalid_lines(self, context: ValidationContext, error_data: E) -> set[int]:
        """Retourne les indices des lignes invalides extraits depuis error_data.errors."""
        return {error["line_idx"] for error in self._get_errors(error_data)}


class BatchCheck[E: ErrorData](Check[E]):
    """
    Check abstrait pour correction en batch (toutes les lignes en une requête).

    Fournit une implémentation concrète de `correct()` qui envoie toutes les lignes
    problématiques en une seule requête LLM, puis merge les corrections.

    Type parameters:
        E: Type ErrorData complet (ex: LineCountErrorData)
    """

    @abstractmethod
    def _render_batch_prompt(
        self,
        context: ValidationContext,
        lines_to_correct: list[int],
        attempt: int,
        use_reasoning: bool,
    ) -> tuple[str, str]:
        """Génère le prompt pour corriger un batch de lignes."""
        ...

    @abstractmethod
    def _validate_batch_output(
        self,
        llm_output: str,
        lines_to_correct: list[int],
        corrected: dict[int, str],
    ) -> bool:
        """
        Valide la sortie LLM batch et remplit corrected si valide.

        Args:
            llm_output: Sortie brute du LLM
            lines_to_correct: Indices des lignes demandées
            corrected: Dict à remplir avec les corrections si valide

        Returns:
            True si la sortie est valide et corrected a été rempli
        """
        ...

    @abstractmethod
    def _get_batch_context_name(self) -> str:
        """Retourne le nom de contexte pour les logs de retry."""
        ...

    @override
    def correct(self, context: ValidationContext, error_data: E) -> dict[int, str]:
        """Corrige toutes les lignes problématiques en une seule requête LLM."""
        if context.llm is None:
            raise ValueError(
                "Correction impossible: context.llm est None (mode lecture seule)"
            )

        lines_to_correct = sorted(self.get_invalid_lines(context, error_data))
        logger.info(
            f"[{type(self).__name__}] Correction de {len(lines_to_correct)} ligne(s) "
            f"pour chunk {context.chunk.index}"
        )

        corrected: dict[int, str] = {}

        def render_prompt(attempt: int, use_reasoning: bool) -> tuple[str, str]:
            return self._render_batch_prompt(
                context, lines_to_correct, attempt, use_reasoning
            )

        def validate_result(llm_output: str) -> bool:
            return self._validate_batch_output(llm_output, lines_to_correct, corrected)

        success, _ = retry_with_reasoning(
            context=context,
            render_prompt=render_prompt,
            validate_result=validate_result,
            context_name=self._get_batch_context_name(),
            max_attempts=2,
        )

        result = dict(context.translated_texts)

        if not success:
            logger.error(
                f"[{type(self).__name__}] ❌ Échec correction après 2 tentatives "
                f"pour chunk {context.chunk.index}, lignes: {lines_to_correct}"
            )
            return result

        result.update(corrected)
        logger.info(
            f"[{type(self).__name__}] ✅ Correction réussie: "
            f"{len(corrected)} lignes corrigées"
        )
        return result
