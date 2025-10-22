"""
Système de glossaire unifié pour cohérence terminologique.

Ce module fournit un glossaire qui combine :
- Apprentissage automatique depuis paires texte/traduction
- Validation post-traduction et détection de conflits
- Export formaté pour injection dans prompts LLM
- Persistance JSON avec reload automatique

Utilisé à la fois pour :
- Phase 1 : Apprentissage automatique des traductions
- Phase 2 : Injection du glossaire dans le prompt d'affinage
- Validation : Détection d'incohérences terminologiques
"""

import json
import re
from pathlib import Path
from typing import Optional
from collections import defaultdict


class Glossary:
    """
    Glossaire unifié pour cohérence terminologique.

    Gère l'apprentissage automatique, la validation et l'export de traductions
    de noms propres et termes techniques pour garantir la cohérence.

    Features:
    - learn(): Apprentissage terme par terme
    - learn_pair(): Apprentissage depuis textes complets avec extraction auto
    - get_translation(): Récupération avec seuil de confiance
    - export_for_prompt(): Export formaté pour prompts LLM
    - get_conflicts(): Détection d'incohérences
    - Persistance JSON automatique

    Example:
        >>> glossary = Glossary(Path("cache/glossary.json"))
        >>> # Apprentissage basique
        >>> glossary.learn("Matrix", "Matrice")
        >>> # Apprentissage depuis paire
        >>> glossary.learn_pair(
        ...     "Dr. Sakamoto activated the Matrix.",
        ...     "Le Dr Sakamoto activa la Matrice."
        ... )
        >>> # Export pour prompt
        >>> prompt_glossary = glossary.export_for_prompt()
        >>> # 'Matrix → Matrice, Sakamoto → Sakamoto'
    """

    def __init__(self, cache_path: Optional[Path] = None):
        """
        Initialise le glossaire.

        Args:
            cache_path: Chemin optionnel pour sauvegarder/charger le glossaire
        """
        self.cache_path = cache_path
        # {terme_source: {traduction: count}}
        self._glossary: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        # {terme_source: traduction_validée}
        self._validated: dict[str, str] = {}

        if cache_path and cache_path.exists():
            self._load_from_cache()

    # =========================================================================
    # API basique : Apprentissage et récupération
    # =========================================================================

    def learn(self, source_term: str, translated_term: str) -> None:
        """
        Enregistre une traduction observée.

        Args:
            source_term: Terme dans la langue source
            translated_term: Traduction observée

        Example:
            >>> glossary.learn("Matrix", "Matrice")
            >>> glossary.learn("Matrix", "Matrice")  # Renforce
            >>> glossary.learn("Matrix", "Système")  # Conflit détecté
        """
        # Ignorer si identiques (ex: noms propres gardés tels quels)
        # if source_term == translated_term:
        #     return

        # Incrémenter le compteur
        self._glossary[source_term][translated_term] += 1

    def get_translation(
        self,
        source_term: str,
        min_confidence: float = 0.5,
    ) -> Optional[str]:
        """
        Récupère la traduction recommandée d'un terme.

        Retourne la traduction validée, ou à défaut la plus fréquente
        si elle dépasse le seuil de confiance.

        Args:
            source_term: Le terme à traduire
            min_confidence: Seuil de confiance minimum (ratio de la traduction dominante)

        Returns:
            Traduction recommandée, ou None si aucune traduction fiable

        Example:
            >>> glossary.get_translation("Matrix")
            'Matrice'
            >>> glossary.get_translation("UnknownTerm")
            None
        """
        # 1. Vérifier s'il y a une traduction validée manuellement
        if source_term in self._validated:
            return self._validated[source_term]

        # 2. Sinon, chercher dans les traductions apprises
        if source_term not in self._glossary:
            return None

        translations = self._glossary[source_term]
        if not translations:
            return None

        # Trouver la traduction la plus fréquente
        total = sum(translations.values())
        most_frequent = max(translations, key=translations.get)  # type: ignore
        frequency = translations[most_frequent]
        confidence = frequency / total

        # Vérifier le seuil de confiance
        if confidence >= min_confidence:
            return most_frequent

        return None

    def validate_translation(
        self,
        source_term: str,
        validated_translation: str,
    ) -> None:
        """
        Valide manuellement une traduction.

        Les traductions validées ont priorité sur celles apprises automatiquement.

        Args:
            source_term: Terme source
            validated_translation: Traduction validée

        Example:
            >>> glossary.validate_translation("Matrix", "Matrice")
            >>> # Cette traduction sera toujours utilisée
        """
        self._validated[source_term] = validated_translation

    # =========================================================================
    # API avancée : Apprentissage depuis paires complètes
    # =========================================================================

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
        # Extraire les termes des deux textes
        original_terms = self._extract_terms(original_text)
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
        - Termes techniques (CamelCase)

        Args:
            text: Texte à analyser

        Returns:
            Liste de termes uniques extraits

        Example:
            >>> glossary._extract_terms("Dr. Sakamoto used the DNA Matrix.")
            ['Sakamoto', 'DNA', 'Matrix']
        """
        terms: set[str] = set()

        # Pattern 1: Mots avec majuscule (mais pas début de phrase)
        # Exclure les titres communs (Dr., Mr., Mrs., etc.)
        words = text.split()
        for i, word in enumerate(words):
            # Nettoyer la ponctuation
            clean_word = re.sub(r"[^\w]", "", word)

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
                    if (
                        i + 1 < len(words)
                        and words[i + 1]
                        and words[i + 1][0].isupper()
                    ):
                        terms.add(clean_word)
                else:
                    # Pas le premier mot → ajouter
                    terms.add(clean_word)

        # Pattern 2: Acronymes (2+ majuscules consécutives)
        acronyms = re.findall(r"\b[A-Z]{2,}\b", text)
        terms.update(acronyms)

        # Pattern 3: Termes techniques (ex: CamelCase)
        camel_case = re.findall(r"\b[A-Z][a-z]+[A-Z][a-zA-Z]*\b", text)
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
        1. Position relative dans le texte (poids 2x)
        2. Similarité de longueur
        3. Similarité phonétique (premières lettres)

        Args:
            original_term: Terme à traduire
            candidate_terms: Termes candidats dans la traduction
            original_text: Texte original complet
            translated_text: Texte traduit complet

        Returns:
            Meilleur terme correspondant ou None (seuil minimum 1.0)
        """
        if not candidate_terms:
            return None

        # Calculer la position relative du terme original (0.0 à 1.0)
        original_pos = original_text.find(original_term)
        if original_pos == -1:
            return None

        original_rel_pos = original_pos / len(original_text)

        # Scorer chaque candidat
        scores: list[tuple[str, float]] = []
        for candidate in candidate_terms:
            score = 0.0

            # Score 1: Position relative similaire
            candidate_pos = translated_text.find(candidate)
            if candidate_pos != -1:
                candidate_rel_pos = candidate_pos / len(translated_text)
                pos_diff = abs(original_rel_pos - candidate_rel_pos)
                score += (1.0 - pos_diff) * 2.0  # Poids 2x

            # Score 2: Longueur similaire
            len_ratio: float = min(len(original_term), len(candidate)) / max(
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

    # =========================================================================
    # Export et validation
    # =========================================================================

    def export_for_prompt(
        self, max_terms: int = 50, min_confidence: float = 0.5
    ) -> str:
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
        terms: list[str] = []

        # Trier par fréquence (termes les plus utilisés en premier)
        for source_term in sorted(
            self._glossary.keys(),
            key=lambda t: sum(self._glossary[t].values()),
            reverse=True,
        ):
            translation = self.get_translation(
                source_term, min_confidence=min_confidence
            )
            if translation:
                terms.append(f"{source_term} → {translation}")

            if len(terms) >= max_terms:
                break

        return ", ".join(terms)

    def get_conflicts(self) -> dict[str, list[str]]:
        """
        Identifie les termes avec des traductions conflictuelles.

        Retourne les termes qui ont plusieurs traductions fréquentes
        (aucune ne domine à >70%).

        Returns:
            Dictionnaire {terme: [traductions_conflictuelles]}

        Example:
            >>> conflicts = glossary.get_conflicts()
            >>> # {'Matrix': ['Matrice', 'Système']} si traductions équilibrées
        """
        conflicts: dict[str, list[str]] = {}

        for source_term, translations in self._glossary.items():
            # Ignorer si déjà validé
            if source_term in self._validated:
                continue

            # Besoin d'au moins 2 traductions
            if len(translations) < 2:
                continue

            # Calculer les ratios
            total = sum(translations.values())
            max_frequency = max(translations.values())
            dominant_ratio = max_frequency / total

            # Si aucune traduction ne domine à >70%, c'est un conflit
            if dominant_ratio < 0.7:
                conflicts[source_term] = sorted(
                    translations.keys(),
                    key=lambda t: translations[t],
                    reverse=True,
                )

        return conflicts

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
            translation = self.get_translation(
                source_term, min_confidence=min_confidence
            )
            if translation:
                result[source_term] = translation
        return result

    def to_dict(self) -> dict[str, str]:
        """
        Exporte le glossaire sous forme de dictionnaire simple.

        Returns:
            Dictionnaire {terme_source: traduction_recommandée}

        Example:
            >>> glossary_dict = glossary.to_dict()
            >>> # {'Matrix': 'Matrice', 'DNA': 'ADN', ...}
        """
        result: dict[str, str] = {}

        # Ajouter les traductions validées
        result.update(self._validated)

        # Ajouter les traductions apprises (si pas déjà validées)
        for source_term in self._glossary:
            if source_term not in result:
                translation = self.get_translation(source_term)
                if translation:
                    result[source_term] = translation

        return result

    # =========================================================================
    # Statistiques et utilitaires
    # =========================================================================

    def get_term_count(self) -> int:
        """
        Retourne le nombre de termes dans le glossaire.

        Returns:
            Nombre de termes uniques
        """
        return len(self._glossary)

    def get_statistics(self) -> dict[str, int]:
        """
        Retourne des statistiques sur le glossaire.

        Returns:
            Dictionnaire avec les stats

        Example:
            >>> stats = glossary.get_statistics()
            >>> print(f"Termes: {stats['total_terms']}, Conflits: {stats['conflicting_terms']}")
        """
        return {
            "total_terms": len(self._glossary),
            "validated_terms": len(self._validated),
            "conflicting_terms": len(self.get_conflicts()),
            "unique_translations": sum(
                len(translations) for translations in self._glossary.values()
            ),
        }

    # =========================================================================
    # Persistance
    # =========================================================================

    def save(self, path: Optional[Path] = None) -> None:
        """
        Sauvegarde le glossaire sur disque.

        Args:
            path: Chemin de sauvegarde (utilise cache_path si non fourni)

        Raises:
            ValueError: Si aucun chemin fourni
        """
        save_path = path or self.cache_path
        if not save_path:
            raise ValueError("No save path provided")

        save_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "glossary": {
                source: dict(translations)
                for source, translations in self._glossary.items()
            },
            "validated": self._validated,
        }

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_from_cache(self) -> None:
        """Charge le glossaire depuis le cache."""
        if not self.cache_path or not self.cache_path.exists():
            return

        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Reconstruire les defaultdicts
            for source, translations in data.get("glossary", {}).items():
                for trans, count in translations.items():
                    self._glossary[source][trans] = count

            self._validated = data.get("validated", {})

        except (json.JSONDecodeError, KeyError, OSError) as e:
            # En cas d'erreur, ignorer et repartir à zéro
            print(f"⚠️ Erreur lors du chargement du glossaire: {e}")
            self._glossary.clear()
            self._validated.clear()

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        stats = self.get_statistics()
        return (
            f"Glossary(\n"
            f"  termes: {stats['total_terms']}\n"
            f"  validés: {stats['validated_terms']}\n"
            f"  conflits: {stats['conflicting_terms']}\n"
            f"  haute confiance (>0.8): {len(self.get_high_confidence_terms())}\n"
            f")"
        )

    def __str__(self) -> str:
        """Représentation textuelle du glossaire."""
        return self.__repr__()
