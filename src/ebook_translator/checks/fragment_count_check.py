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
            return CheckResult(is_valid=True, check_name=self.name)

        # Construire message d'erreur
        first_error = errors[0]
        expected_sep = first_error['expected_fragments'] - 1
        actual_sep = first_error['actual_fragments'] - 1
        text_type = 'Texte continu' if expected_sep == 0 else 'Texte fragmenté'

        error_message = (
            f"Nombre de séparateurs </> incorrect sur {len(errors)} ligne(s)\n"
            f"  • Première erreur: ligne {first_error['line_idx']}\n"
            f"    - Séparateurs attendus: {expected_sep}\n"
            f"    - Séparateurs reçus: {actual_sep}\n"
            f"    - Type: {text_type}"
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

        logger.info(
            f"[FragmentCountCheck] Correction de {len(errors)} ligne(s) "
            f"pour chunk {context.chunk.index} (max {context.max_retries} tentatives)"
        )

        # Retranslater chaque ligne problématique avec retry progressif
        for error in errors:
            line_idx = error["line_idx"]
            original_text = error["original_text"]
            expected_fragments = error["expected_fragments"]
            actual_fragments = error["actual_fragments"]

            # Calculer nombre de séparateurs (pas de segments)
            expected_separators = expected_fragments - 1
            actual_separators = actual_fragments - 1

            # Récupérer la traduction incorrecte actuelle
            incorrect_translation = context.translated_texts.get(line_idx, "")

            # Boucle de retry avec prompts progressifs
            success = False
            for retry_attempt in range(context.max_retries):
                # Choisir template selon tentative
                if retry_attempt == 0:
                    # 1ère tentative : STRICT (positions fixes)
                    template = TemplateNames.Retry_Translation_Template
                    strategy = "STRICT"
                else:
                    # 2ème+ tentative : FLEXIBLE (positions libres)
                    template = TemplateNames.Retry_Translation_Flexible_Template
                    strategy = "FLEXIBLE"

                logger.debug(
                    f"[FragmentCountCheck] Ligne {line_idx}, "
                    f"tentative {retry_attempt + 1}/{context.max_retries} ({strategy})"
                )

                # Générer prompt
                prompt = context.llm.render_prompt(
                    template,
                    target_language=context.target_language,
                    original_text=original_text,
                    incorrect_translation=incorrect_translation,
                    expected_separators=expected_separators,
                    actual_separators=actual_separators,
                )

                # Appel LLM
                llm_context = (
                    f"correction_fragment_chunk_{context.chunk.index:03d}_"
                    f"line_{line_idx}_attempt_{retry_attempt + 1}_{strategy.lower()}"
                )

                try:
                    llm_output = context.llm.query(
                        prompt, original_text, context=llm_context
                    )
                    corrected_line = parse_llm_translation_output("<0/>" + llm_output)
                except Exception as e:
                    logger.warning(
                        f"[FragmentCountCheck] Tentative {retry_attempt + 1} : "
                        f"erreur LLM pour ligne {line_idx}: {e}"
                    )
                    continue  # Essayer prochaine tentative

                if 0 not in corrected_line:
                    logger.warning(
                        f"[FragmentCountCheck] Tentative {retry_attempt + 1} : "
                        f"parsing échoué pour ligne {line_idx}"
                    )
                    continue

                # Vérifier résultat
                corrected_text = corrected_line[0]
                corrected_separators = corrected_text.count(FRAGMENT_SEPARATOR)

                # Validation : NOMBRE EXACT requis (pour les deux stratégies)
                if corrected_separators == expected_separators:
                    result[line_idx] = corrected_text
                    logger.info(
                        f"[FragmentCountCheck] ✅ Ligne {line_idx} corrigée "
                        f"(tentative {retry_attempt + 1} {strategy}, "
                        f"{corrected_separators} séparateurs)"
                    )
                    success = True
                    break  # Succès, passer à prochaine ligne
                else:
                    logger.warning(
                        f"[FragmentCountCheck] Tentative {retry_attempt + 1} {strategy} : "
                        f"nombre incorrect (attendu {expected_separators}, "
                        f"reçu {corrected_separators})"
                    )
                    # Mettre à jour pour prochaine tentative
                    incorrect_translation = corrected_text

            if not success:
                # Toutes tentatives épuisées
                logger.error(
                    f"[FragmentCountCheck] ❌ Ligne {line_idx} NON corrigée après "
                    f"{context.max_retries} tentatives "
                    f"(attendu {expected_separators} séparateurs)"
                )
                # Garder traduction originale incorrecte
                # Le pipeline la rejettera lors de la re-validation

        return result
