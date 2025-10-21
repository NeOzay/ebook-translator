"""
Moteur de retry automatique pour corriger les erreurs de segmentation.

Ce module utilise le LLM pour corriger automatiquement les erreurs
de type FragmentMismatchError en re-soumettant avec un prompt renforcé.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from ..logger import get_logger
from ..htmlpage.constants import FRAGMENT_SEPARATOR

if TYPE_CHECKING:
    from ..llm import LLM

logger = get_logger(__name__)


@dataclass
class CorrectionResult:
    """
    Résultat d'une tentative de correction automatique.

    Attributes:
        success: True si la correction a réussi
        corrected_text: Texte corrigé (None si échec)
        attempts: Nombre de tentatives effectuées
        error_message: Message d'erreur (None si succès)
    """

    success: bool
    corrected_text: Optional[str]
    attempts: int
    error_message: Optional[str] = None


class RetryEngine:
    """
    Moteur de retry automatique pour corriger les erreurs de segmentation.

    Ce moteur détecte les erreurs FragmentMismatchError et tente de les
    corriger en re-soumettant la requête au LLM avec un prompt renforcé
    qui explique clairement l'erreur et comment la corriger.
    """

    def __init__(self, llm: "LLM", max_retries: int = 2):
        """
        Initialise le moteur de retry.

        Args:
            llm: Instance du LLM à utiliser pour les corrections
            max_retries: Nombre maximum de tentatives de correction (défaut: 2)
        """
        self.llm = llm
        self.max_retries = max_retries

    def attempt_correction(
        self,
        original_fragments: list[str],
        incorrect_segments: list[str],
        target_language: str,
        original_text: str,
    ) -> CorrectionResult:
        """
        Tente de corriger une erreur de segmentation via retry LLM.

        Args:
            original_fragments: Liste des fragments originaux
            incorrect_segments: Liste des segments incorrects retournés par le LLM
            target_language: Langue cible de la traduction
            original_text: Texte original complet

        Returns:
            CorrectionResult avec le résultat de la correction
        """
        expected_count = len(original_fragments)
        actual_count = len(incorrect_segments)

        logger.warning(
            f"Tentative de correction automatique : "
            f"attendu {expected_count} fragments, reçu {actual_count}"
        )

        # Tentative 1 : Prompt renforcé avec analyse de l'erreur
        for attempt in range(1, self.max_retries + 1):
            logger.info(f"Tentative de correction #{attempt}/{self.max_retries}")

            try:
                if attempt == 1:
                    # Première tentative : prompt renforcé
                    corrected_text = self._retry_with_reinforced_prompt(
                        original_fragments,
                        incorrect_segments,
                        target_language,
                        original_text,
                    )
                else:
                    # Deuxième tentative : prompt ultra-strict (fragment par fragment)
                    corrected_text = self._retry_with_strict_prompt(
                        original_fragments, target_language, original_text
                    )

                # Valider le résultat
                if corrected_text:
                    segments = corrected_text.split(FRAGMENT_SEPARATOR)
                    if len(segments) == expected_count:
                        logger.info(
                            f"✅ Correction réussie après {attempt} tentative(s)"
                        )
                        return CorrectionResult(
                            success=True,
                            corrected_text=corrected_text,
                            attempts=attempt,
                        )
                    else:
                        logger.warning(
                            f"Tentative #{attempt} : toujours incorrect "
                            f"({len(segments)} segments au lieu de {expected_count})"
                        )

            except Exception as e:
                logger.error(f"Erreur lors de la tentative #{attempt} : {e}")

        # Échec après tous les retries
        logger.error(
            f"❌ Échec de correction après {self.max_retries} tentatives. "
            f"Le segment sera ignoré."
        )
        return CorrectionResult(
            success=False,
            corrected_text=None,
            attempts=self.max_retries,
            error_message=f"Échec après {self.max_retries} tentatives",
        )

    def _retry_with_reinforced_prompt(
        self,
        original_fragments: list[str],
        incorrect_segments: list[str],
        target_language: str,
        original_text: str,
    ) -> Optional[str]:
        """
        Première tentative : prompt renforcé avec analyse de l'erreur.

        Args:
            original_fragments: Fragments originaux
            incorrect_segments: Segments incorrects
            target_language: Langue cible
            original_text: Texte original

        Returns:
            Texte corrigé ou None
        """
        # Analyser l'erreur
        expected_count = len(original_fragments)
        actual_count = len(incorrect_segments)
        diff = expected_count - actual_count

        if diff > 0:
            analysis = f"Vous avez fusionné {diff} fragment(s)"
        elif diff < 0:
            analysis = f"Vous avez divisé en trop ({abs(diff)} segment(s) en trop)"
        else:
            analysis = (
                "Le nombre de segments est correct mais la structure est incorrecte"
            )

        # Construire le prompt renforcé
        prompt = self.llm.render_prompt(
            "retry_translation.jinja",
            target_language=target_language,
            original_fragments=original_fragments,
            incorrect_segments=incorrect_segments,
            expected_count=expected_count,
            actual_count=actual_count,
            analysis=analysis,
        )

        # Re-soumettre au LLM
        response = self.llm.query(prompt, "<0/>" + original_text)

        # Parser la réponse
        from ..translation.parser import parse_llm_translation_output

        try:
            translations = parse_llm_translation_output(response)
            # Reconstruire avec les séparateurs
            return translations[0]
        except ValueError as e:
            logger.error(f"Échec du parsing de la réponse renforcée : {e}")
            return None

    def _retry_with_strict_prompt(
        self, original_fragments: list[str], target_language: str, original_text: str
    ) -> Optional[str]:
        """
        Deuxième tentative : prompt ultra-strict (fragment par fragment).

        Args:
            original_fragments: Fragments originaux
            target_language: Langue cible
            original_text: Texte original

        Returns:
            Texte corrigé ou None
        """
        prompt = self.llm.render_prompt(
            "retry_translation_strict.jinja",
            target_language=target_language,
            original_fragments=original_fragments,
        )

        # Re-soumettre au LLM
        response = self.llm.query(prompt, original_text)

        # Parser la réponse
        from ..translation.parser import parse_llm_translation_output

        try:
            translations = parse_llm_translation_output(response)
            # Reconstruire avec les séparateurs
            return FRAGMENT_SEPARATOR.join(
                translations[i] for i in sorted(translations.keys())
            )
        except ValueError as e:
            logger.error(f"Échec du parsing de la réponse stricte : {e}")
            return None
