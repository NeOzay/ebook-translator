"""
Détecteur de segments non traduits (restés en langue source).

Ce module utilise des heuristiques simples pour détecter des segments
qui semblent ne pas avoir été traduits :
- Mots courants en anglais (the, and, to, etc.)
- Mots courants dans d'autres langues sources
- Ratio de caractères alphabétiques latins vs non-latins
"""

import re
from dataclasses import dataclass
from typing import Optional


# Mots courants en anglais (les 100+ mots les plus fréquents)
COMMON_ENGLISH_WORDS = {
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
    "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
    "this", "but", "his", "by", "from", "they", "we", "say", "her", "she",
    "or", "an", "will", "my", "one", "all", "would", "there", "their",
    "what", "so", "up", "out", "if", "about", "who", "get", "which", "go",
    "me", "when", "make", "can", "like", "time", "no", "just", "him", "know",
    "take", "people", "into", "year", "your", "good", "some", "could", "them",
    "see", "other", "than", "then", "now", "look", "only", "come", "its",
    "over", "think", "also", "back", "after", "use", "two", "how", "our",
    "work", "first", "well", "way", "even", "new", "want", "because", "any",
    "these", "give", "day", "most", "us", "is", "was", "are", "been", "has",
    "had", "were", "said", "did", "having", "may", "should", "could", "must",
}

# Patterns typiques de phrases en anglais
ENGLISH_PATTERNS = [
    r"\b(the|a|an)\s+\w+",  # Articles + mot
    r"\b(is|are|was|were|am)\s+",  # Verbe être
    r"\b(have|has|had)\s+",  # Verbe avoir
    r"\b(will|would|could|should|might|may)\s+",  # Modaux
    r"\b(I|you|he|she|it|we|they)\s+",  # Pronoms sujet
]


@dataclass
class UntranslatedSegment:
    """
    Représente un segment potentiellement non traduit.

    Attributes:
        text: Le texte suspect
        confidence: Niveau de confiance (0.0 à 1.0) que c'est non traduit
        reason: Raison de la détection
        position: Position dans le texte (optionnel)
    """
    text: str
    confidence: float
    reason: str
    position: Optional[int] = None

    def __str__(self) -> str:
        return (
            f"⚠️ Segment potentiellement non traduit (confiance: {self.confidence:.0%})\n"
            f"  • Texte: \"{self.text[:100]}{'...' if len(self.text) > 100 else ''}\"\n"
            f"  • Raison: {self.reason}"
        )


class UntranslatedDetector:
    """
    Détecteur de segments non traduits.

    Utilise plusieurs heuristiques pour détecter des segments qui semblent
    ne pas avoir été traduits depuis la langue source.

    Example:
        >>> detector = UntranslatedDetector(source_lang="en", target_lang="fr")
        >>> issues = detector.detect("The cat is sleeping. Le chien mange.")
        >>> for issue in issues:
        ...     print(issue)
    """

    def __init__(self, source_lang: str = "en", target_lang: str = "fr"):
        """
        Initialise le détecteur.

        Args:
            source_lang: Code de la langue source (ex: "en")
            target_lang: Code de la langue cible (ex: "fr")
        """
        self.source_lang = source_lang.lower()
        self.target_lang = target_lang.lower()

    def detect(
        self,
        translated_text: str,
        min_confidence: float = 0.6,
    ) -> list[UntranslatedSegment]:
        """
        Détecte les segments potentiellement non traduits.

        Args:
            translated_text: Le texte traduit à analyser
            min_confidence: Seuil de confiance minimum pour rapporter un problème

        Returns:
            Liste des segments suspects
        """
        issues: list[UntranslatedSegment] = []

        # Seulement pour anglais → autre langue actuellement
        if self.source_lang != "en":
            return issues

        # 1. Détecter phrases complètes en anglais
        sentences = self._split_sentences(translated_text)
        for i, sentence in enumerate(sentences):
            confidence = self._calculate_english_confidence(sentence)

            if confidence >= min_confidence:
                issues.append(UntranslatedSegment(
                    text=sentence.strip(),
                    confidence=confidence,
                    reason=f"Phrase détectée comme anglais (confiance: {confidence:.0%})",
                    position=i,
                ))

        return issues

    def _split_sentences(self, text: str) -> list[str]:
        """
        Découpe le texte en phrases.

        Args:
            text: Le texte à découper

        Returns:
            Liste de phrases
        """
        # Découpage simple sur ponctuation forte
        sentences = re.split(r'[.!?]+\s+', text)
        return [s for s in sentences if s.strip()]

    def _calculate_english_confidence(self, text: str) -> float:
        """
        Calcule la probabilité qu'un texte soit en anglais.

        Utilise plusieurs heuristiques :
        1. Ratio de mots courants en anglais
        2. Présence de patterns grammaticaux anglais
        3. Longueur du texte (plus c'est long, plus on est sûr)

        Args:
            text: Le texte à analyser

        Returns:
            Confiance entre 0.0 (certainement pas anglais) et 1.0 (certainement anglais)
        """
        if not text.strip():
            return 0.0

        text_lower = text.lower()
        words = re.findall(r'\b[a-z]+\b', text_lower)

        if not words:
            return 0.0

        # 1. Ratio de mots courants en anglais
        english_words = sum(1 for word in words if word in COMMON_ENGLISH_WORDS)
        word_ratio = english_words / len(words)

        # 2. Présence de patterns grammaticaux anglais
        pattern_matches = sum(
            1 for pattern in ENGLISH_PATTERNS
            if re.search(pattern, text_lower)
        )
        pattern_score = min(pattern_matches / len(ENGLISH_PATTERNS), 1.0)

        # 3. Bonus pour texte long (plus de confiance)
        length_bonus = min(len(words) / 10, 0.2)  # Max +0.2 pour 10+ mots

        # Combiner les scores (pondération)
        confidence = (
            word_ratio * 0.6 +      # 60% du poids sur les mots
            pattern_score * 0.3 +   # 30% sur les patterns
            length_bonus            # 10% bonus longueur
        )

        return min(confidence, 1.0)

    def check_translation_pair(
        self,
        original: str,
        translated: str,
        min_similarity: float = 0.9,
    ) -> Optional[UntranslatedSegment]:
        """
        Vérifie si la traduction semble identique à l'original (non traduite).

        Args:
            original: Texte original
            translated: Texte traduit
            min_similarity: Seuil de similarité pour considérer comme non traduit

        Returns:
            UntranslatedSegment si détection, None sinon
        """
        # Normaliser pour comparaison
        orig_normalized = self._normalize_for_comparison(original)
        trans_normalized = self._normalize_for_comparison(translated)

        # Si strictement identiques
        if orig_normalized == trans_normalized:
            return UntranslatedSegment(
                text=translated,
                confidence=1.0,
                reason="Traduction strictement identique à l'original",
            )

        # Si très similaires (>90% de caractères identiques)
        if orig_normalized and trans_normalized:
            similarity = self._calculate_similarity(orig_normalized, trans_normalized)

            if similarity >= min_similarity:
                return UntranslatedSegment(
                    text=translated,
                    confidence=similarity,
                    reason=f"Traduction très similaire à l'original ({similarity:.0%})",
                )

        return None

    def _normalize_for_comparison(self, text: str) -> str:
        """
        Normalise le texte pour comparaison.

        Supprime la ponctuation, les espaces multiples, et met en minuscules.

        Args:
            text: Texte à normaliser

        Returns:
            Texte normalisé
        """
        # Supprimer ponctuation et mettre en minuscules
        normalized = re.sub(r'[^\w\s]', '', text.lower())
        # Supprimer espaces multiples
        normalized = ' '.join(normalized.split())
        return normalized

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Calcule la similarité entre deux textes (ratio de caractères identiques).

        Args:
            text1: Premier texte
            text2: Deuxième texte

        Returns:
            Similarité entre 0.0 et 1.0
        """
        if not text1 or not text2:
            return 0.0

        # Simple ratio de caractères communs
        shorter = min(len(text1), len(text2))
        longer = max(len(text1), len(text2))

        common_chars = sum(
            1 for i in range(shorter)
            if text1[i] == text2[i]
        )

        return common_chars / longer
