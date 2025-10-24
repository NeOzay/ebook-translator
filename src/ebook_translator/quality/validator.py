"""
Validateur de qualité sémantique pour traductions.

Ce module orchestre toutes les vérifications de qualité sémantique :
détection de segments non traduits, cohérence terminologique, etc.

Usage optionnel, indépendant du pipeline principal de validation.
"""

from typing import Optional
from pathlib import Path

from ..logger import get_logger
from .untranslated_detector import UntranslatedDetector
from .terminology_checker import TerminologyChecker
from ..glossary import Glossary

logger = get_logger(__name__)


class QualityValidator:
    """
    Validateur de qualité sémantique pour traductions.

    Ce validateur orchestre toutes les vérifications de qualité sémantique :
    - Détection de segments non traduits
    - Vérification de cohérence terminologique
    - Glossaire automatique

    Usage optionnel, à utiliser manuellement après traduction.

    Example:
        >>> validator = QualityValidator(source_lang="en", target_lang="fr")
        >>> validator.validate_translation(
        ...     original="The Matrix is active",
        ...     translated="La Matrice est active",
        ... )
        >>> issues = validator.get_all_issues()
    """

    def __init__(
        self,
        source_lang: str = "en",
        target_lang: str = "fr",
        glossary_path: Optional[Path] = None,
        enable_untranslated_detection: bool = True,
        enable_terminology_check: bool = True,
        enable_glossary: bool = True,
    ):
        """
        Initialise le validateur.

        Args:
            source_lang: Code de la langue source
            target_lang: Code de la langue cible
            glossary_path: Chemin pour le glossaire (optionnel)
            enable_untranslated_detection: Activer détection de segments non traduits
            enable_terminology_check: Activer vérification cohérence terminologique
            enable_glossary: Activer le glossaire automatique
        """
        self.source_lang = source_lang
        self.target_lang = target_lang

        # Initialiser les composants selon les flags
        self.untranslated_detector: Optional[UntranslatedDetector] = None
        if enable_untranslated_detection:
            self.untranslated_detector = UntranslatedDetector(source_lang, target_lang)

        self.terminology_checker: Optional[TerminologyChecker] = None
        if enable_terminology_check:
            self.terminology_checker = TerminologyChecker()

        self.glossary: Optional[Glossary] = None
        if enable_glossary:
            self.glossary = Glossary(cache_path=glossary_path)

        # Compteurs de problèmes
        self.untranslated_count = 0
        self.terminology_issues_count = 0

    def validate_translation(
        self,
        original: str,
        translated: str,
        position: Optional[int] = None,
    ) -> bool:
        """
        Valide une paire original → traduit.

        Effectue toutes les vérifications activées et enregistre les résultats.

        Args:
            original: Texte original
            translated: Texte traduit
            position: Position dans le document (optionnel)

        Returns:
            True si tout est OK, False si des problèmes sont détectés
        """
        has_issues = False

        # 1. Vérifier si non traduit
        if self.untranslated_detector:
            # Détecter dans le texte traduit
            issues = self.untranslated_detector.detect(translated, min_confidence=0.7)
            if issues:
                has_issues = True
                self.untranslated_count += len(issues)
                for issue in issues:
                    logger.warning(f"Position {position}: {issue}")

            # Vérifier si identique à l'original
            same_issue = self.untranslated_detector.check_translation_pair(
                original, translated, min_similarity=0.9
            )
            if same_issue:
                has_issues = True
                self.untranslated_count += 1
                logger.warning(f"Position {position}: {same_issue}")

        # 2. Extraire et vérifier termes
        if self.terminology_checker:
            self.terminology_checker.extract_terms_from_pair(
                original, translated, position
            )

        # 3. Apprendre pour le glossaire
        if self.glossary and self.terminology_checker:
            # Utiliser le TerminologyChecker pour extraire les termes
            # et les ajouter au glossaire
            source_terms = self.terminology_checker._extract_proper_nouns(original)
            trans_terms = self.terminology_checker._extract_proper_nouns(translated)

            for i, source_term in enumerate(source_terms):
                if i < len(trans_terms):
                    self.glossary.learn(source_term, trans_terms[i])

        return not has_issues

    def get_all_issues(self) -> dict[str, list]:
        """
        Récupère tous les problèmes détectés.

        Returns:
            Dictionnaire {type_problème: [liste_problèmes]}
        """
        issues: dict[str, list] = {}

        # Problèmes de cohérence terminologique
        if self.terminology_checker:
            terminology_issues = self.terminology_checker.get_issues()
            if terminology_issues:
                issues["terminology"] = terminology_issues
                self.terminology_issues_count = len(terminology_issues)

        # Conflits de glossaire
        if self.glossary:
            conflicts = self.glossary.get_conflicts()
            if conflicts:
                issues["glossary_conflicts"] = [
                    f"{term}: {', '.join(translations)}"
                    for term, translations in conflicts.items()
                ]

        return issues

    def generate_report(self) -> str:
        """
        Génère un rapport de validation texte.

        Returns:
            Rapport formaté
        """
        lines = ["=" * 60, "📊 RAPPORT DE VALIDATION DE TRADUCTION", "=" * 60, ""]

        # Statistiques générales
        lines.append("## Statistiques")
        lines.append(f"  • Segments non traduits détectés: {self.untranslated_count}")
        lines.append(f"  • Problèmes de cohérence terminologique: {self.terminology_issues_count}")

        if self.glossary:
            stats = self.glossary.get_statistics()
            lines.append(f"  • Termes dans le glossaire: {stats['total_terms']}")
            lines.append(f"  • Termes validés: {stats['validated_terms']}")
            lines.append(f"  • Conflits terminologiques: {stats['conflicting_terms']}")

        lines.append("")

        # Problèmes détectés
        issues = self.get_all_issues()

        if issues:
            lines.append("## Problèmes détectés")
            lines.append("")

            # Incohérences terminologiques
            if "terminology" in issues:
                lines.append("### ⚠️ Incohérences terminologiques")
                lines.append("")
                for issue in issues["terminology"][:10]:  # Limiter à 10
                    lines.append(str(issue))
                    lines.append("")

                if len(issues["terminology"]) > 10:
                    lines.append(f"... et {len(issues['terminology']) - 10} autres")
                    lines.append("")

            # Conflits de glossaire
            if "glossary_conflicts" in issues:
                lines.append("### ⚠️ Conflits de glossaire")
                lines.append("")
                for conflict in issues["glossary_conflicts"][:10]:
                    lines.append(f"  • {conflict}")

                if len(issues["glossary_conflicts"]) > 10:
                    lines.append(f"... et {len(issues['glossary_conflicts']) - 10} autres")

        else:
            lines.append("✅ Aucun problème majeur détecté !")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)

    def save_glossary(self, path: Optional[Path] = None) -> None:
        """
        Sauvegarde le glossaire appris.

        Args:
            path: Chemin de sauvegarde (optionnel)
        """
        if self.glossary:
            self.glossary.save(path)
            logger.info(f"✅ Glossaire sauvegardé: {path or self.glossary.cache_path}")

    def export_glossary_dict(self) -> dict[str, str]:
        """
        Exporte le glossaire sous forme de dictionnaire.

        Returns:
            Dictionnaire {terme_source: traduction_recommandée}
        """
        if self.glossary:
            return self.glossary.to_dict()
        return {}
