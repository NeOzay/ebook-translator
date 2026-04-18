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
from ebook_translator.segmentation.chapter_chunk import ChapterChunk, ChapterPartChunk
from ebook_translator.validator.analysis_validator import AnalysisValidator

logger = get_logger(__name__)


class AnalysisChecks(Check[AnalysisErrorData]):
    @property
    @override
    def name(self) -> str:
        return "analysis_checks"

    @override
    def validate(self, context: ValidationContext) -> CheckResult[AnalysisErrorData]:
        match context.chunk:
            case ChapterChunk(name=str(name)):
                chunk_name = name
            case ChapterPartChunk(chapter=ChapterChunk(name=str(name))):
                chunk_name = name
            case _:
                chunk_name = "unknown"

        logger.debug(f"[AnalysisChecks] 🔍 Début validation pour {chunk_name}")

        response = context.translated_texts[0]
        error = AnalysisErrorData(
            missing_sections=[],
            invalid_json=False,
            json_error_message="",
        )

        # 1. Parser JSON
        try:
            analysis_dict = json.loads(response)
        except json.JSONDecodeError as e:
            error_message = str(e)
            logger.warning(
                f"[AnalysisChecks] ⚠️ JSON invalide pour {chunk_name}: {error_message[:100]}"
            )
            error.invalid_json = True
            error.json_error_message = error_message
            return FailedResult(
                check_name=self.name,
                error_data=error,
            )

        # 2. Valider structure ContexteTraduction
        analysis_dict, error.missing_sections = AnalysisValidator.validate(
            analysis_dict, context.chunk
        )
        if error.missing_sections:
            # Limiter l'affichage à 5 premières sections
            missing_preview = error.missing_sections[:5]
            more = len(error.missing_sections) - 5

            logger.warning(
                f"[AnalysisChecks] ⚠️ Sections manquantes pour {chunk_name}: "
                f"{', '.join(missing_preview)}"
                + (f" (+{more} autres)" if more > 0 else "")
            )
            return FailedResult(
                check_name=self.name,
                error_data=error,
                error_message=f"Missing sections in analysis for {chunk_name}: {', '.join(error.missing_sections)}",
            )

        # 3. Mettre à jour le contexte avec le JSON validé
        context.translated_texts[0] = json.dumps(analysis_dict, ensure_ascii=False)

        # Succès : compter les termes du glossaire pour stats
        num_terms = len(analysis_dict.get("glossaire", []))
        logger.info(
            f"[AnalysisChecks] ✅ Validation réussie pour {chunk_name} "
            f"({num_terms} termes au glossaire)"
        )
        return SuccessResult(check_name=self.name)

    @override
    def correct(
        self, context: ValidationContext, error_data: AnalysisErrorData
    ) -> dict[int, str]:
        if context.llm is None:
            raise ValueError(
                "Correction impossible: context.llm est None (mode lecture seule)"
            )

        match context.chunk:
            case ChapterChunk(name=str(name)):
                name = name
            case ChapterPartChunk(chapter=ChapterChunk(name=str(name))):
                name = name
            case _:
                name = "unknown"

        # Log détaillé selon le type d'erreur
        if error_data.invalid_json:
            logger.info(f"[AnalysisChecks] 🔄 Correction JSON invalide pour {name}")
        elif error_data.missing_sections:
            missing_count = len(error_data.missing_sections)
            logger.info(
                f"[AnalysisChecks] 🔄 Correction sections manquantes pour {name} "
                f"({missing_count} section(s))"
            )

        def render_prompt(attempt: int, use_reasoning: bool) -> tuple[str, str]:
            if context.llm is None:
                raise ValueError("context.llm est None")

            mode = "reasoning" if use_reasoning else "normal"
            logger.debug(
                f"[AnalysisChecks] 📝 Génération prompt (tentative {attempt}, mode {mode})"
            )

            # Choisir le template selon le type d'erreur
            if error_data.invalid_json:
                return context.llm.renderer.render_retry_analysis_invalid_json(
                    chapter_name=name,
                    target_language=context.target_language,
                    json_error_message=error_data.json_error_message,
                    invalid_response=context.translated_texts[0],
                )
            else:  # missing_sections
                return context.llm.renderer.render_retry_analysis_missing_sections(
                    chapter_name=name,
                    target_language=context.target_language,
                    missing_sections=error_data.missing_sections,
                    incomplete_response=context.translated_texts[0],
                    chapter_text=context.chunk.prepare_for_prompt([]),
                )

        def validate_result(llm_output: str) -> bool:
            try:
                analysis_dict = json.loads(llm_output)
            except json.JSONDecodeError as e:
                logger.debug(
                    f"[AnalysisChecks] ❌ JSON invalide dans retry: {str(e)[:80]}"
                )
                return False

            _, missing_sections = AnalysisValidator.validate(analysis_dict)

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
            logger.info(f"[AnalysisChecks] ✅ Correction réussie pour {name}")
        else:
            logger.error(
                f"[AnalysisChecks] ❌ Échec de la correction après 2 tentatives pour {name}"
            )

        return context.translated_texts

    @override
    def get_invalid_lines(
        self, context: ValidationContext, error_data: AnalysisErrorData
    ) -> set[int]:
        return set()
