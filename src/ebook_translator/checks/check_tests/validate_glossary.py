import json
from typing import override

from ebook_translator.checks.check_tests.base import (
    AnalysisErrorData,
    Check,
    CheckResult,
    FailedResult,
    SuccessResult,
    ValidationContext,
)
from ebook_translator.checks.retry_helper import retry_with_reasoning
from ebook_translator.logger import get_logger
from ebook_translator.validator.glossary_validator import GlossaryValidator

logger = get_logger(__name__)


class GlossaryChecks(Check[AnalysisErrorData]):
    @property
    @override
    def name(self) -> str:
        return "glossary_checks"

    @override
    def validate(self, context: ValidationContext) -> CheckResult[AnalysisErrorData]:
        chunk_index = context.chunk.index
        logger.debug(
            f"[GlossaryChecks] 🔍 Début validation pour le chunk {chunk_index}"
        )

        response = context.translated_texts[0]
        error = AnalysisErrorData(
            missing_sections=[],
            invalid_json=False,
            json_error_message="",
        )

        # 1. Parser JSON
        try:
            glossary_dict = json.loads(response)
        except json.JSONDecodeError as e:
            error_message = str(e)
            logger.warning(
                f"[AnalysisChecks] ⚠️ JSON invalide pour chunk {chunk_index}: {error_message[:100]}"
            )
            error.invalid_json = True
            error.json_error_message = error_message
            return FailedResult(
                check_name=self.name,
                error_data=error,
            )

        # 2. Valider structure ContexteTraduction
        glossary_dict, error.missing_sections = GlossaryValidator.validate(
            glossary_dict
        )
        if error.missing_sections:
            # Limiter l'affichage à 5 premières sections
            missing_preview = error.missing_sections[:5]
            more = len(error.missing_sections) - 5

            logger.warning(
                f"[AnalysisChecks] ⚠️ Sections manquantes pour le chunk {chunk_index}: "
                f"{', '.join(missing_preview)}"
                + (f" (+{more} autres)" if more > 0 else "")
            )
            return FailedResult(
                check_name=self.name,
                error_data=error,
                error_message=f"Missing sections for glossary (chunk {chunk_index}): {', '.join(error.missing_sections)}",
            )

        # 3. Mettre à jour le contexte avec le JSON validé
        context.translated_texts[0] = json.dumps(glossary_dict, ensure_ascii=False)

        return SuccessResult(check_name=self.name)

    @override
    def correct(
        self, context: ValidationContext, error_data: AnalysisErrorData
    ) -> dict[int, str]:
        if context.llm is None:
            raise ValueError(
                "Correction impossible: context.llm est None (mode lecture seule)"
            )
        chunk_index = context.chunk.index

        # Log détaillé selon le type d'erreur
        if error_data.invalid_json:
            logger.info(
                f"[AnalysisChecks] 🔄 Correction JSON invalide pour le chunk {chunk_index}"
            )

        def render_prompt(attempt: int, use_reasoning: bool) -> tuple[str, str]:
            if context.llm is None:
                raise ValueError("context.llm est None")

            mode = "reasoning" if use_reasoning else "normal"
            logger.debug(
                f"[AnalysisChecks] 📝 Génération prompt (tentative {attempt}, mode {mode})"
            )

            # Choisir le template selon le type d'erreur
            return context.llm.renderer.render_retry_analysis_invalid_json(
                chapter_name="glossary",
                target_language=context.target_language,
                json_error_message=error_data.json_error_message,
                invalid_response=context.translated_texts[0],
            )

        def validate_result(llm_output: str) -> bool:
            try:
                analysis_dict = json.loads(llm_output)
            except json.JSONDecodeError as e:
                logger.debug(
                    f"[AnalysisChecks] ❌ JSON invalide dans retry: {str(e)[:80]}"
                )
                return False

            _, missing_sections = GlossaryValidator.validate(analysis_dict)

            if missing_sections:
                # Limiter l'affichage à 3 sections pour ne pas polluer les logs
                preview = missing_sections[:3]
                more = len(missing_sections) - 3
                logger.debug(
                    f"[AnalysisChecks] ⚠️ Retry - sections manquantes: "
                    f"{', '.join(preview)}" + (f" (+{more})" if more > 0 else "")
                )
                return False

            logger.debug("[AnalysisChecks] ✅ Validation retry réussie")
            return True

        # Exécuter retry avec reasoning (2 tentatives max)
        logger.debug(
            "[AnalysisChecks] 🔄 Lancement retry_with_reasoning (max 2 tentatives)"
        )

        success, _ = retry_with_reasoning(
            context=context,
            render_prompt=render_prompt,
            validate_result=validate_result,
            context_name="AnalysisChecks",
            max_attempts=2,
        )

        if success:
            logger.info(
                f"[AnalysisChecks] ✅ Correction réussie pour le chunk {chunk_index}"
            )
        else:
            logger.error(
                f"[AnalysisChecks] ❌ Échec de la correction après 2 tentatives pour le chunk {chunk_index}"
            )

        return context.translated_texts

    @override
    def get_invalid_lines(
        self, context: ValidationContext, error_data: AnalysisErrorData
    ) -> set[int]:
        return set()
