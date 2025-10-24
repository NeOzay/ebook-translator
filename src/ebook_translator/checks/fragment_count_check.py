"""
Check de validation du nombre de fragments.

Ce check vérifie que le nombre de séparateurs </> correspond entre
texte original et traduit, et corrige automatiquement en retranslant
les lignes problématiques avec un prompt strict.
"""

from typing import TYPE_CHECKING, cast

from ..logger import get_logger
from .base import (
    CheckResult,
    ValidationContext,
    ErrorData,
    FragmentCountErrorData,
    FragmentErrorDetail,
)

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

FRAGMENT_SEPARATOR = "</>"


class FragmentCountCheck:
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
        >>> result = check.validate(context)
        >>> if not result.is_valid:
        ...     corrected = check.correct(context, result.error_data)
    """

    @property
    def name(self) -> str:
        """Nom unique du check."""
        return "fragment_count"

    def validate(self, context: ValidationContext) -> CheckResult:
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
        errors = []

        # Vérifier chaque paire (original, traduit)
        for line_idx, translated_text in context.translated_texts.items():
            if line_idx not in context.original_texts:
                # Ligne traduite sans original (ne devrait pas arriver)
                continue

            original_text = context.original_texts[line_idx]
            expected_count = original_text.count(FRAGMENT_SEPARATOR) + 1
            actual_count = translated_text.count(FRAGMENT_SEPARATOR) + 1

            if expected_count != actual_count:
                error_detail: FragmentErrorDetail = {
                    "line_idx": line_idx,
                    "original_text": original_text,
                    "translated_text": translated_text,
                    "expected_fragments": expected_count,
                    "actual_fragments": actual_count,
                }
                errors.append(error_detail)

        if not errors:
            return CheckResult(is_valid=True, check_name=self.name)

        # Construire message d'erreur
        first_error = errors[0]
        error_message = (
            f"Fragment mismatch détecté sur {len(errors)} ligne(s)\n"
            f"  • Première erreur: ligne {first_error['line_idx']} "
            f"(attendu {first_error['expected_fragments']} fragments, "
            f"reçu {first_error['actual_fragments']} fragments)"
        )

        error_data: FragmentCountErrorData = {"errors": errors}

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
        Corrige en retranslant les lignes avec mauvais nombre de fragments.

        Cette méthode retraduit chaque ligne problématique individuellement
        avec un prompt strict qui insiste lourdement sur la préservation
        des séparateurs </>.

        Args:
            context: Contexte de validation
            error_data: Données d'erreur avec liste d'erreurs de fragments

        Returns:
            Nouvelles traductions {line_index: translated_text} incluant corrections

        Raises:
            Exception: Si context.llm est None ou traduction échoue

        Example:
            >>> # Contexte avec ligne 0 ayant mauvais nombre de fragments
            >>> error_data = {
            ...     "errors": [{
            ...         "line_idx": 0,
            ...         "original_text": "Hello</>world",
            ...         "expected_fragments": 2,
            ...     }]
            ... }
            >>> corrected = check.correct(context, error_data)
            >>> # corrected[0] contiendra maintenant un séparateur </>
        """
        from ..config import TemplateNames
        from ..translation.parser import parse_llm_translation_output

        if context.llm is None:
            raise ValueError(
                "Correction impossible: context.llm est None (mode lecture seule)"
            )

        # Type narrowing: on sait que error_data est FragmentCountErrorData
        typed_error_data = cast(FragmentCountErrorData, error_data)
        errors = typed_error_data["errors"]
        result = dict(context.translated_texts)

        logger.debug(
            f"[FragmentCountCheck] Correction de {len(errors)} ligne(s) "
            f"pour chunk {context.chunk.index}"
        )

        # Retranslater chaque ligne problématique individuellement
        for error in errors:
            line_idx = error["line_idx"]
            original_text = error["original_text"]
            expected_fragments = error["expected_fragments"]
            actual_fragments = error["actual_fragments"]

            # Préparer les fragments pour le template de retry
            original_fragments = original_text.split(FRAGMENT_SEPARATOR)

            # Récupérer la traduction incorrecte actuelle
            incorrect_translation = context.translated_texts.get(line_idx, "")
            incorrect_segments = (
                incorrect_translation.split(FRAGMENT_SEPARATOR)
                if incorrect_translation
                else []
            )

            # Utiliser le template de retry spécialisé pour fragments
            prompt = context.llm.render_prompt(
                TemplateNames.Retry_Translation_Template,
                target_language=context.target_language,
                expected_count=expected_fragments,
                actual_count=actual_fragments,
                original_fragments=original_fragments,
                incorrect_segments=incorrect_segments,
                analysis=f"Attendu {expected_fragments} fragments, reçu {actual_fragments}",
            )

            logger.debug(
                f"[FragmentCountCheck] Correction ligne {line_idx} "
                f"(attendu {expected_fragments} fragments, reçu {actual_fragments})"
            )

            # Appel LLM (pas de source_content, tout est dans le template)
            llm_context = (
                f"correction_fragment_chunk_{context.chunk.index:03d}_line_{line_idx}"
            )
            llm_output = context.llm.query(prompt, original_text, context=llm_context)
            corrected_line = parse_llm_translation_output(llm_output)

            if 0 not in corrected_line:
                logger.warning(
                    f"[FragmentCountCheck] Correction ligne {line_idx} "
                    f"n'a pas retourné la ligne 0"
                )
                continue  # Garder l'ancienne traduction

            # Vérifier que la correction a le bon nombre de fragments
            corrected_text = corrected_line[0]
            corrected_count = corrected_text.count(FRAGMENT_SEPARATOR) + 1

            if corrected_count == expected_fragments:
                result[line_idx] = corrected_text
                logger.debug(
                    f"[FragmentCountCheck] Ligne {line_idx} corrigée avec succès"
                )
            else:
                logger.warning(
                    f"[FragmentCountCheck] Correction ligne {line_idx} toujours invalide "
                    f"(attendu {expected_fragments}, reçu {corrected_count})"
                )
                # La re-validation du pipeline détectera cette erreur

        return result
