from typing import override

from ...logger import get_logger
from .base import (
    CheckResult,
    FailedResult,
    SentenceErrorData,
    SentenceErrorDetail,
    SuccessResult,
    ValidationContext,
)
from .intermediate import BatchCheck
from .line_count_check import validate_retry_indices

logger = get_logger(__name__)


# =============================================================================
# Fonctions utilitaires pour analyse de phrases
# =============================================================================


def _has_sentence_mismatch(
    original_text: str,
    translated_text: str,
    previous_text: str = "",
) -> bool:
    """
    Détecte si le nombre de phrases diffère entre original et traduit.
    Args:
        original_text: Texte original
        translated_text: Texte traduit
        previous_text: Texte traduit précédent (optionnel)
    Returns:
        True si le nombre de phrases diffère, False sinon
    """
    # Compter les phrases dans chaque version
    original_sentences = _count_sentences(original_text)
    translated_sentences = _count_sentences(translated_text)
    previous_sentences = _count_sentences(previous_text)

    # Détection d'incohérence:
    # 1. Nombre de phrases différent entre original et traduit
    # OU
    # 2. Nombre de phrases différent entre précédent et traduit (si précédent existe)
    has_sentence_mismatch = original_sentences != translated_sentences or (
        previous_sentences != 0 and previous_sentences != translated_sentences
    )
    return has_sentence_mismatch


def _count_sentences(text: str) -> int:
    """
    Compte le nombre de phrases dans un texte.

    Cette fonction utilise une heuristique simple basée sur les signes de
    ponctuation de fin de phrase (.!?). Elle ne gère pas les cas complexes
    comme les abréviations (Dr., Mr., etc.) ou les nombres décimaux.

    Args:
        text: Texte à analyser

    Returns:
        Nombre de phrases détectées (basé sur ponctuation finale)

    Examples:
        >>> _count_sentences("Hello. World!")
        2
        >>> _count_sentences("Bonjour")
        0
        >>> _count_sentences("Dr. Smith works here.")  # Compte 2 (limitation)
        2

    Note:
        Cette fonction peut surestimer le nombre de phrases si le texte
        contient des abréviations avec points. C'est une limitation connue.
    """
    import re

    # Expression régulière pour détecter les fins de phrases
    # Détecte un ou plusieurs signes parmi: . ! ?
    sentence_endings = re.compile(r"[.!?]+")
    sentences = sentence_endings.split(text.strip())

    # Filtrer les phrases vides (résultant du split)
    # Exemple: "Hello." → ["Hello", ""] → filtré → ["Hello"]
    sentences = [s for s in sentences if s.strip()]
    return len(sentences)


def _check_length_similarity(a: str, b: str, threshold: float) -> bool:
    """
    Vérifie si deux textes ont une longueur similaire.

    Compare les longueurs de deux textes en calculant le ratio du plus court
    sur le plus long. Si le ratio est >= threshold, les longueurs sont considérées
    similaires.

    Args:
        a: Premier texte
        b: Deuxième texte
        threshold: Seuil minimal de similarité (0.0 à 1.0)

    Returns:
        True si le ratio de longueur >= threshold, False sinon

    Examples:
        >>> _check_length_similarity("Hello", "Bonjour", 0.5)
        True  # 5/7 = 0.71 >= 0.5
        >>> _check_length_similarity("Hi", "Very long sentence", 0.5)
        False  # 2/18 = 0.11 < 0.5
        >>> _check_length_similarity("", "test", 0.5)
        False  # Texte vide

    Note:
        Retourne False si l'un des textes est vide pour éviter division par zéro.
    """
    len_a = len(a)
    len_b = len(b)

    # Cas limites: texte vide → pas de similarité
    if len_a == 0 or len_b == 0:
        return False

    # Calcul du ratio: plus_court / plus_long (toujours <= 1.0)
    ratio = min(len_a, len_b) / max(len_a, len_b)
    return ratio >= threshold


class SentenceCheck(BatchCheck[SentenceErrorData]):
    """
    Vérifie que le nombre de phrases est cohérent entre original et traduction.

    Ce check détecte les traductions où le nombre de phrases diffère de l'original,
    ce qui peut indiquer une fusion/division de phrases incorrecte.
    """

    # ==========================================================================
    # Constantes de validation
    # ==========================================================================

    # Nombre minimal de mots pour activer le check (évite faux positifs sur textes courts)
    MIN_WORDS_THRESHOLD = 20

    # Ratio minimal de longueur entre original et traduction (50%)
    # Si ratio < 0.5, la traduction est probablement trop courte/longue
    ORIGINAL_LENGTH_RATIO = 0.5

    # Ratio minimal de longueur entre traduction précédente et actuelle (90%)
    # Si ratio < 0.9, la retraduction a significativement changé la longueur
    PREVIOUS_LENGTH_RATIO = 0.9

    @property
    def name(self) -> str:
        return "sentence_check"

    @override
    def validate(self, context: ValidationContext) -> CheckResult[SentenceErrorData]:
        """
        Valide que le nombre de phrases est cohérent.

        Stratégie de détection:
        1. Comparer nombre de phrases (original vs traduit)
        2. Si précédente traduction existe, comparer aussi (précédent vs traduit)
        3. Filtrer les faux positifs via:
           - Ignorer lignes courtes (< 20 mots)
           - Vérifier ratio de longueur (évite détections sur abréviations)

        Args:
            context: Contexte de validation

        Returns:
            CheckResult avec erreurs détectées ou is_valid=True
        """
        errors: list[SentenceErrorDetail] = []

        # Vérifier chaque paire (original, traduit)
        for line_idx, translated_text in context.translated_texts.items():
            # Skip si ligne traduite sans original (ne devrait jamais arriver)
            if line_idx not in context.original_texts:
                continue

            original_text = context.original_texts[line_idx]

            # Récupérer traduction précédente si disponible (phase refined)
            if context.previous_translated_texts:
                # Accès par index dans la liste des valeurs du body
                # body est un dict[TagKey, str], on convertit en liste pour accès par index
                previous_translations = list(
                    context.previous_translated_texts.body.values()
                )
                previous_text = (
                    previous_translations[line_idx]
                    if line_idx < len(previous_translations)
                    else ""
                )
            else:
                previous_text = ""

            if _has_sentence_mismatch(original_text, translated_text, previous_text):
                # Filtre 1: Ignorer lignes courtes (trop de faux positifs)
                # Les abréviations causent des comptes incorrects sur textes courts
                if len(original_text.split()) < self.MIN_WORDS_THRESHOLD:
                    continue

                # Filtre 2: Vérifier ratio de longueur pour éviter faux positifs
                # Si longueur très différente, c'est probablement une vraie erreur
                original_too_different = not _check_length_similarity(
                    original_text, translated_text, self.ORIGINAL_LENGTH_RATIO
                )
                previous_too_different = previous_text and not _check_length_similarity(
                    previous_text, translated_text, self.PREVIOUS_LENGTH_RATIO
                )

                if original_too_different or previous_too_different:
                    error_detail = SentenceErrorDetail(
                        line_idx=line_idx,
                        original_text=original_text,
                        translated_text=translated_text,
                        previous_translated_text=previous_text,
                    )
                    errors.append(error_detail)

        # Retourner résultat
        if not errors:
            return SuccessResult(check_name=self.name)

        return FailedResult(
            check_name=self.name,
            error_message="Nombre de phrases incorrect",
            error_data=SentenceErrorData(errors=errors),
        )

    @override
    def get_invalid_lines(
        self, context: ValidationContext, error_data: SentenceErrorData
    ) -> set[int]:
        """
        Extrait les indices des lignes invalides depuis error_data.

        Args:
            context: Contexte de validation (non utilisé)
            error_data: Données d'erreur contenant la liste des erreurs

        Returns:
            Set des indices de lignes avec nombre de phrases incorrect
        """
        return {detail["line_idx"] for detail in error_data.errors}

    # =========================================================================
    # Implémentations des méthodes abstraites de BatchCheck
    # =========================================================================

    @override
    def _render_batch_prompt(
        self,
        context: ValidationContext,
        lines_to_correct: list[int],
        attempt: int,
        use_reasoning: bool,
    ) -> tuple[str, str]:
        if context.llm is None:
            raise ValueError("LLM is None")
        return context.llm.renderer.render_retry_sentence(
            chunk=context.chunk,
            target_language=context.target_language,
            previous_translation=context.previous_translated_texts,
            missing_indices=lines_to_correct,
        )

    @override
    def _validate_batch_output(
        self,
        llm_output: str,
        lines_to_correct: list[int],
        corrected: dict[int, str],
    ) -> bool:
        try:
            from ...translation.parser import parse_llm_translation_output

            parsed = parse_llm_translation_output(llm_output)
            is_valid, retry_error = validate_retry_indices(parsed, lines_to_correct)
            if is_valid:
                corrected.update(parsed)
                return True
            logger.warning(f"[SentenceCheck] Validation échouée: {retry_error}")
            return False
        except Exception as e:
            logger.error(f"[SentenceCheck] ❌ Erreur parsing: {e}")
            return False

    @override
    def _get_batch_context_name(self) -> str:
        return "sentence_lines"
