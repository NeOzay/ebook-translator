"""
Module de validation post-traduction.

Ce module fournit des outils pour valider la qualité des traductions :
- Détection de segments non traduits (restés en langue source)
- Vérification de la cohérence terminologique
- Détection de noms propres incohérents
- Glossaire automatique pour termes techniques et noms propres
"""

from .untranslated_detector import UntranslatedDetector, UntranslatedSegment
from .terminology_checker import TerminologyChecker, TerminologyIssue
from .glossary import AutoGlossary
from .validator import TranslationValidator

__all__ = [
    "UntranslatedDetector",
    "UntranslatedSegment",
    "TerminologyChecker",
    "TerminologyIssue",
    "AutoGlossary",
    "TranslationValidator",
]
