"""
Système de validation sémantique optionnel.

Ce module fournit des outils pour analyser la qualité sémantique des traductions,
indépendamment du pipeline de validation structurelle principal.

Fonctionnalités:
- Détection de segments non traduits (restés en langue source)
- Vérification de cohérence terminologique (même terme → traductions différentes)
- Glossaire automatique des termes techniques et noms propres

Usage:
    Ce module est **optionnel** et doit être utilisé manuellement après traduction.
    Il n'est PAS intégré dans le pipeline principal (validation/).

Example:
    >>> from ebook_translator.quality import QualityValidator
    >>> validator = QualityValidator(source_lang="en", target_lang="fr")
    >>> for original, translated in translations:
    ...     validator.validate_translation(original, translated)
    >>> print(validator.generate_report())
"""

from .validator import QualityValidator
from .untranslated_detector import UntranslatedDetector, UntranslatedSegment
from .terminology_checker import TerminologyChecker, TerminologyIssue

__all__ = [
    "QualityValidator",
    "UntranslatedDetector",
    "UntranslatedSegment",
    "TerminologyChecker",
    "TerminologyIssue",
]
