"""
Vérificateur de cohérence terminologique.

Ce module détecte les incohérences de traduction où le même terme source
est traduit de différentes manières dans le même contexte.

Exemples :
- "Matrix" → "Matrice" puis "Système"
- "Dr. Sakamoto" → "Dr Sakamoto" puis "Docteur Sakamoto"
"""

import re
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict


@dataclass
class TerminologyIssue:
    """
    Représente une incohérence terminologique détectée.

    Attributes:
        source_term: Le terme dans la langue source
        translations: Les différentes traductions trouvées
        positions: Positions où chaque traduction apparaît
        confidence: Niveau de confiance de l'incohérence (0.0 à 1.0)
        suggestion: Traduction recommandée (la plus fréquente)
    """
    source_term: str
    translations: list[str]
    positions: dict[str, list[int]] = field(default_factory=dict)
    confidence: float = 1.0
    suggestion: Optional[str] = None

    def __post_init__(self):
        """Calcule la suggestion (traduction la plus fréquente)."""
        if not self.suggestion and self.positions:
            # Compter les occurrences
            counts = {trans: len(pos) for trans, pos in self.positions.items()}
            # Prendre la plus fréquente
            self.suggestion = max(counts, key=counts.get)  # type: ignore

    def __str__(self) -> str:
        trans_list = "\n".join(
            f"    - \"{trans}\" ({len(pos)} fois)"
            for trans, pos in self.positions.items()
        )
        suggestion_str = f"\n  💡 Suggestion: utiliser \"{self.suggestion}\" partout" if self.suggestion else ""

        return (
            f"⚠️ Incohérence terminologique détectée:\n"
            f"  • Terme source: \"{self.source_term}\"\n"
            f"  • Traductions trouvées:\n{trans_list}"
            f"{suggestion_str}"
        )


class TerminologyChecker:
    """
    Vérificateur de cohérence terminologique.

    Suit les traductions de termes spécifiques (noms propres, termes techniques)
    et détecte les incohérences.

    Example:
        >>> checker = TerminologyChecker()
        >>> checker.add_pair("Matrix", "Matrice", position=0)
        >>> checker.add_pair("Matrix", "Système", position=10)
        >>> issues = checker.get_issues()
        >>> for issue in issues:
        ...     print(issue)
    """

    def __init__(self, min_occurrences: int = 2):
        """
        Initialise le vérificateur.

        Args:
            min_occurrences: Nombre minimum d'occurrences pour signaler une incohérence
        """
        self.min_occurrences = min_occurrences
        # {terme_source: {traduction: [positions]}}
        self._translations: dict[str, dict[str, list[int]]] = defaultdict(
            lambda: defaultdict(list)
        )

    def add_pair(
        self,
        source_term: str,
        translated_term: str,
        position: Optional[int] = None,
    ) -> None:
        """
        Enregistre une paire source → traduction.

        Args:
            source_term: Terme dans la langue source
            translated_term: Traduction
            position: Position dans le document (optionnel)
        """
        # Normaliser les termes pour comparaison
        source_normalized = self._normalize_term(source_term)
        trans_normalized = self._normalize_term(translated_term)

        # Ignorer si identiques (noms propres non traduits, etc.)
        if source_normalized == trans_normalized:
            return

        # Enregistrer la traduction
        pos = position if position is not None else len(
            self._translations[source_normalized]
        )
        self._translations[source_normalized][trans_normalized].append(pos)

    def get_issues(self, min_confidence: float = 0.7) -> list[TerminologyIssue]:
        """
        Récupère toutes les incohérences détectées.

        Args:
            min_confidence: Seuil de confiance minimum

        Returns:
            Liste des incohérences terminologiques
        """
        issues: list[TerminologyIssue] = []

        for source_term, translations in self._translations.items():
            # Besoin d'au moins 2 traductions différentes
            if len(translations) < 2:
                continue

            # Vérifier le nombre total d'occurrences
            total_occurrences = sum(len(positions) for positions in translations.values())
            if total_occurrences < self.min_occurrences:
                continue

            # Calculer la confiance de l'incohérence
            # Plus il y a de traductions différentes, plus on est confiant qu'il y a un problème
            confidence = self._calculate_inconsistency_confidence(translations)

            if confidence >= min_confidence:
                issues.append(TerminologyIssue(
                    source_term=source_term,
                    translations=list(translations.keys()),
                    positions=dict(translations),
                    confidence=confidence,
                ))

        return sorted(issues, key=lambda x: x.confidence, reverse=True)

    def extract_terms_from_pair(
        self,
        source_text: str,
        translated_text: str,
        position: Optional[int] = None,
    ) -> None:
        """
        Extrait et enregistre automatiquement les termes d'une paire source/traduction.

        Détecte :
        - Noms propres (commençant par une majuscule)
        - Termes techniques (mots avec majuscules internes: "Matrix", "API", etc.)
        - Noms de lieux, personnages, etc.

        Args:
            source_text: Texte source
            translated_text: Texte traduit
            position: Position dans le document
        """
        # Extraire noms propres du texte source
        source_terms = self._extract_proper_nouns(source_text)
        translated_terms = self._extract_proper_nouns(translated_text)

        # Tenter de matcher les termes source → traduction
        # Stratégie simple : même ordre d'apparition
        for i, source_term in enumerate(source_terms):
            if i < len(translated_terms):
                self.add_pair(source_term, translated_terms[i], position)

    def _extract_proper_nouns(self, text: str) -> list[str]:
        """
        Extrait les noms propres d'un texte.

        Détecte :
        - Mots commençant par une majuscule (sauf début de phrase)
        - Séquences de mots capitalisés (ex: "Dr. Sakamoto")
        - Acronymes (ex: "NASA", "API")

        Args:
            text: Le texte à analyser

        Returns:
            Liste de noms propres
        """
        proper_nouns = []

        # Pattern pour noms propres: majuscule + minuscules (ou tout en majuscules pour acronymes)
        # Mais pas au début de phrase
        pattern = r'(?<!\.\s)(?<!\n)(?<!\A)\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*|[A-Z]{2,})\b'

        matches = re.finditer(pattern, text)
        for match in matches:
            noun = match.group(1).strip()
            # Filtrer les mots courants qui commencent souvent les phrases
            if noun.lower() not in {'the', 'a', 'an', 'this', 'that', 'these', 'those', 'i'}:
                proper_nouns.append(noun)

        return proper_nouns

    def _normalize_term(self, term: str) -> str:
        """
        Normalise un terme pour comparaison.

        Args:
            term: Le terme à normaliser

        Returns:
            Terme normalisé
        """
        # Supprimer espaces multiples et trim
        normalized = ' '.join(term.split())
        return normalized

    def _calculate_inconsistency_confidence(
        self,
        translations: dict[str, list[int]],
    ) -> float:
        """
        Calcule la confiance qu'il y a une incohérence.

        Plus il y a de traductions différentes ET plus elles sont équilibrées,
        plus on est confiant qu'il y a un problème.

        Args:
            translations: Dictionnaire {traduction: [positions]}

        Returns:
            Confiance entre 0.0 et 1.0
        """
        num_translations = len(translations)
        if num_translations < 2:
            return 0.0

        # Compter les occurrences
        counts = [len(positions) for positions in translations.values()]
        total = sum(counts)

        # Si une traduction domine à >80%, moins confiant (peut être légitime)
        max_count = max(counts)
        dominant_ratio = max_count / total

        if dominant_ratio > 0.8:
            # Moins confiant, mais toujours signaler
            return 0.7

        # Sinon, confiance élevée
        # Plus il y a de traductions différentes, plus c'est suspect
        return min(0.7 + (num_translations - 2) * 0.1, 1.0)

    def get_glossary(self) -> dict[str, str]:
        """
        Génère un glossaire des traductions recommandées.

        Retourne un dictionnaire {terme_source: traduction_recommandée}
        basé sur la traduction la plus fréquente.

        Returns:
            Dictionnaire de glossaire
        """
        glossary: dict[str, str] = {}

        for source_term, translations in self._translations.items():
            if not translations:
                continue

            # Trouver la traduction la plus fréquente
            counts = {trans: len(pos) for trans, pos in translations.items()}
            most_frequent = max(counts, key=counts.get)  # type: ignore

            glossary[source_term] = most_frequent

        return glossary

    def clear(self) -> None:
        """Efface toutes les données enregistrées."""
        self._translations.clear()
