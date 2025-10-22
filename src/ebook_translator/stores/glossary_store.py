"""
Extension d'AutoGlossary pour apprentissage automatique depuis paires texte complet.

Ce module enrichit AutoGlossary avec la capacité d'apprendre automatiquement
depuis des paires (texte_original, texte_traduit) complètes, en extrayant
les noms propres et termes techniques.
"""

import re
from pathlib import Path
from typing import Optional

from ..validation.glossary import AutoGlossary


class GlossaryStore(AutoGlossary):
    """
    Glossaire enrichi qui apprend depuis des paires de textes complets.

    Extension d'AutoGlossary avec extraction automatique de termes depuis
    les traductions complètes (Phase 1). Utilisé pour Phase 2 affinage.

    Features:
    - Extraction automatique de noms propres (majuscules, acronymes)
    - Extraction de termes techniques (patterns spécifiques)
    - Alignement automatique source → traduction
    - Export formaté pour injection dans prompts

    Example:
        >>> glossary = GlossaryStore(Path("cache/glossary.json"))
        >>> original = "Dr. Sakamoto activated the Matrix."
        >>> translated = "Le Dr Sakamoto activa la Matrice."
        >>> glossary.learn_pair(original, translated)
        >>> glossary.get_translation("Matrix")
        'Matrice'
        >>> print(glossary.export_for_prompt())
        'Matrix → Matrice, Dr. Sakamoto → Dr Sakamoto'
    """

    def __init__(self, cache_path: Optional[Path] = None):
        """
        Initialise le GlossaryStore.

        Args:
            cache_path: Chemin optionnel pour sauvegarder/charger le glossaire
        """
        super().__init__(cache_path)

    def learn_pair(self, original_text: str, translated_text: str) -> None:
        """
        Apprend depuis une paire (texte_original, texte_traduit).

        Extrait automatiquement les noms propres et termes techniques,
        puis les aligne pour apprendre les traductions.

        Args:
            original_text: Texte dans la langue source
            translated_text: Texte traduit

        Example:
            >>> glossary.learn_pair(
            ...     "Dr. Sakamoto activated the Temporal Matrix.",
            ...     "Le Dr Sakamoto activa la Matrice Temporelle."
            ... )
            >>> # Apprend: Sakamoto → Sakamoto, Matrix → Matrice
        """
        # Extraire les termes du texte original
        original_terms = self._extract_terms(original_text)

        # Extraire les termes du texte traduit
        translated_terms = self._extract_terms(translated_text)

        # Alignement simple : chercher les correspondances
        for original_term in original_terms:
            # Chercher le terme original dans le texte traduit
            # (peut être gardé tel quel, ex: noms propres)
            if original_term in translated_text:
                # Terme gardé identique
                self.learn(original_term, original_term)
            else:
                # Chercher la meilleure correspondance par similarité
                best_match = self._find_best_match(
                    original_term, translated_terms, original_text, translated_text
                )
                if best_match:
                    self.learn(original_term, best_match)

    def _extract_terms(self, text: str) -> list[str]:
        """
        Extrait les noms propres et termes techniques d'un texte.

        Critères d'extraction:
        - Mots commençant par une majuscule (hors début de phrase)
        - Acronymes (2+ majuscules consécutives)
        - Termes techniques (patterns spécifiques)

        Args:
            text: Texte à analyser

        Returns:
            Liste de termes uniques extraits

        Example:
            >>> glossary._extract_terms("Dr. Sakamoto used the DNA Matrix.")
            ['Sakamoto', 'DNA', 'Matrix']
        """
        terms = set()

        # Pattern 1: Mots avec majuscule (mais pas début de phrase)
        # Exclure les titres communs (Dr., Mr., Mrs., etc.)
        words = text.split()
        for i, word in enumerate(words):
            # Nettoyer la ponctuation
            clean_word = re.sub(r'[^\w]', '', word)

            # Skip mots vides ou trop courts
            if len(clean_word) < 2:
                continue

            # Skip titres communs
            if clean_word in ["Dr", "Mr", "Mrs", "Ms", "Prof", "Sir", "Lady"]:
                continue

            # Chercher mots avec majuscule
            if clean_word and clean_word[0].isupper():
                # Si c'est le premier mot, vérifier qu'il soit suivi d'un autre mot capitalisé
                if i == 0:
                    if i + 1 < len(words) and words[i + 1] and words[i + 1][0].isupper():
                        terms.add(clean_word)
                else:
                    # Pas le premier mot → ajouter
                    terms.add(clean_word)

        # Pattern 2: Acronymes (2+ majuscules consécutives)
        acronyms = re.findall(r'\b[A-Z]{2,}\b', text)
        terms.update(acronyms)

        # Pattern 3: Termes techniques (ex: CamelCase)
        camel_case = re.findall(r'\b[A-Z][a-z]+[A-Z][a-zA-Z]*\b', text)
        terms.update(camel_case)

        return sorted(list(terms))

    def _find_best_match(
        self,
        original_term: str,
        candidate_terms: list[str],
        original_text: str,
        translated_text: str,
    ) -> Optional[str]:
        """
        Trouve la meilleure correspondance pour un terme original.

        Utilise plusieurs heuristiques:
        1. Position relative dans le texte
        2. Similarité de longueur
        3. Similarité phonétique (premières lettres)

        Args:
            original_term: Terme à traduire
            candidate_terms: Termes candidats dans la traduction
            original_text: Texte original complet
            translated_text: Texte traduit complet

        Returns:
            Meilleur terme correspondant ou None

        Example:
            >>> glossary._find_best_match(
            ...     "Matrix",
            ...     ["Matrice", "Système"],
            ...     "activated the Matrix",
            ...     "activa la Matrice"
            ... )
            'Matrice'
        """
        if not candidate_terms:
            return None

        # Calculer la position relative du terme original (0.0 à 1.0)
        original_pos = original_text.find(original_term)
        if original_pos == -1:
            return None

        original_rel_pos = original_pos / len(original_text)

        # Scorer chaque candidat
        scores = []
        for candidate in candidate_terms:
            score = 0.0

            # Score 1: Position relative similaire
            candidate_pos = translated_text.find(candidate)
            if candidate_pos != -1:
                candidate_rel_pos = candidate_pos / len(translated_text)
                pos_diff = abs(original_rel_pos - candidate_rel_pos)
                score += (1.0 - pos_diff) * 2.0  # Poids 2x

            # Score 2: Longueur similaire
            len_ratio = min(len(original_term), len(candidate)) / max(
                len(original_term), len(candidate)
            )
            score += len_ratio

            # Score 3: Première lettre similaire
            if original_term[0].lower() == candidate[0].lower():
                score += 0.5

            scores.append((candidate, score))

        # Retourner le meilleur match (seuil minimum 1.0)
        best = max(scores, key=lambda x: x[1])
        return best[0] if best[1] >= 1.0 else None

    def export_for_prompt(self, max_terms: int = 50, min_confidence: float = 0.5) -> str:
        """
        Exporte le glossaire au format texte pour injection dans un prompt.

        Format: "term1 → translation1, term2 → translation2, ..."

        Args:
            max_terms: Nombre maximum de termes à exporter (défaut: 50)
            min_confidence: Seuil de confiance minimum (défaut: 0.5)

        Returns:
            String formaté pour injection dans le prompt

        Example:
            >>> print(glossary.export_for_prompt())
            'Matrix → Matrice, Dr. Sakamoto → Dr Sakamoto, DNA → ADN'
        """
        terms = []

        # Trier par fréquence (termes les plus utilisés en premier)
        for source_term in sorted(
            self._glossary.keys(),
            key=lambda t: sum(self._glossary[t].values()),
            reverse=True,
        ):
            translation = self.get_translation(source_term, min_confidence=min_confidence)
            if translation:
                terms.append(f"{source_term} → {translation}")

            if len(terms) >= max_terms:
                break

        return ", ".join(terms)

    def get_term_count(self) -> int:
        """
        Retourne le nombre de termes dans le glossaire.

        Returns:
            Nombre de termes uniques
        """
        return len(self._glossary)

    def get_high_confidence_terms(self, min_confidence: float = 0.8) -> dict[str, str]:
        """
        Récupère les termes avec haute confiance.

        Args:
            min_confidence: Seuil de confiance (défaut: 0.8)

        Returns:
            Dictionnaire {terme_source: traduction}

        Example:
            >>> high_conf = glossary.get_high_confidence_terms(min_confidence=0.9)
            >>> # Seulement les termes traduits de manière très cohérente
        """
        result = {}
        for source_term in self._glossary:
            translation = self.get_translation(source_term, min_confidence=min_confidence)
            if translation:
                result[source_term] = translation
        return result

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        stats = self.get_statistics()
        return (
            f"GlossaryStore(\n"
            f"  termes: {stats['total_terms']}\n"
            f"  validés: {stats['validated_terms']}\n"
            f"  conflits: {stats['conflicting_terms']}\n"
            f"  haute confiance (>0.8): {len(self.get_high_confidence_terms())}\n"
            f")"
        )
