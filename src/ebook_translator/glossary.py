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
from collections import defaultdict
from pathlib import Path


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

    def __init__(self, cache_path: Path | None = None):
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

        Filtre automatiquement les mots grammaticaux et mots très courts
        pour éviter la pollution du glossaire.

        Args:
            source_term: Terme dans la langue source
            translated_term: Traduction observée

        Example:
            >>> glossary.learn("Matrix", "Matrice")
            >>> glossary.learn("Matrix", "Matrice")  # Renforce
            >>> glossary.learn("Matrix", "Système")  # Conflit détecté
            >>> glossary.learn("the", "le")  # Ignoré (stopword)
        """
        from .glossary_filters import should_exclude_from_glossary

        # Filtrer mots grammaticaux et mots courts automatiquement
        if should_exclude_from_glossary(source_term):
            return  # Ignorer silencieusement

        # Ignorer si identiques (ex: noms propres gardés tels quels)
        # if source_term == translated_term:
        #     return

        # Incrémenter le compteur
        self._glossary[source_term][translated_term] += 1

    def get_translation(
        self,
        source_term: str,
        min_confidence: float = 0.5,
    ) -> str | None:
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
        most_frequent = max(translations, key=lambda t: translations[t])
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
        result: dict[str, str] = {}
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
    # Nettoyage du glossaire
    # =========================================================================

    def clean_stopwords(self) -> int:
        """
        Retire les mots grammaticaux du glossaire existant.

        Utilise should_exclude_from_glossary() pour identifier les termes
        à supprimer (articles, pronoms, prépositions, etc.).

        Returns:
            Nombre de termes supprimés

        Example:
            >>> removed_count = glossary.clean_stopwords()
            >>> print(f"{removed_count} stopwords supprimés")
        """
        from .glossary_filters import should_exclude_from_glossary

        terms_to_remove = [
            term for term in self._glossary if should_exclude_from_glossary(term)
        ]

        for term in terms_to_remove:
            del self._glossary[term]
            # Supprimer aussi des validations si présent
            if term in self._validated:
                del self._validated[term]

        return len(terms_to_remove)

    def remove_low_confidence_terms(self, min_occurrences: int = 2) -> int:
        """
        Retire les termes avec très peu d'occurrences (probables erreurs d'extraction).

        Args:
            min_occurrences: Nombre minimum d'occurrences total (défaut: 2)

        Returns:
            Nombre de termes supprimés

        Example:
            >>> removed_count = glossary.remove_low_confidence_terms(min_occurrences=2)
            >>> print(f"{removed_count} termes à faible confiance supprimés")
        """
        terms_to_remove: list[str] = []

        for source_term, translations in self._glossary.items():
            total_occurrences = sum(translations.values())
            if total_occurrences < min_occurrences:
                terms_to_remove.append(source_term)

        for term in terms_to_remove:
            del self._glossary[term]
            # Supprimer aussi des validations si présent
            if term in self._validated:
                del self._validated[term]

        return len(terms_to_remove)

    def clean_all(
        self, min_occurrences: int = 2, verbose: bool = True
    ) -> dict[str, int]:
        """
        Nettoie le glossaire en appliquant tous les filtres.

        Applique dans l'ordre :
        1. Suppression des stopwords grammaticaux
        2. Suppression des termes à faible confiance

        Args:
            min_occurrences: Seuil minimum pour remove_low_confidence_terms (défaut: 2)
            verbose: Affiche les statistiques de nettoyage (défaut: True)

        Returns:
            Dictionnaire avec le nombre de suppressions par catégorie

        Example:
            >>> stats = glossary.clean_all()
            >>> # {'stopwords': 123, 'low_confidence': 45, 'total': 168}
        """
        from .logger import get_logger

        logger = get_logger(__name__)

        if verbose:
            stats_before = self.get_statistics()
            logger.info("🧹 Nettoyage du glossaire...")
            logger.info(f"  Avant : {stats_before['total_terms']} termes")

        # Étape 1 : Stopwords
        stopwords_removed = self.clean_stopwords()
        if verbose:
            logger.info(f"  Stopwords supprimés : {stopwords_removed}")

        # Étape 2 : Faible confiance
        low_conf_removed = self.remove_low_confidence_terms(min_occurrences)
        if verbose:
            logger.info(f"  Faible confiance supprimés : {low_conf_removed}")

        if verbose:
            stats_after = self.get_statistics()
            total_removed = stopwords_removed + low_conf_removed
            logger.info(f"  Après : {stats_after['total_terms']} termes")
            logger.info(f"✅ Total supprimé : {total_removed} termes")

        return {
            "stopwords": stopwords_removed,
            "low_confidence": low_conf_removed,
            "total": stopwords_removed + low_conf_removed,
        }

    # =========================================================================
    # Persistance
    # =========================================================================

    def save(self, path: Path | None = None) -> None:
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
            with open(self.cache_path, encoding="utf-8") as f:
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
