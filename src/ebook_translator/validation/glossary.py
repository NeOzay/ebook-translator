"""
Système de glossaire automatique pour noms propres et termes techniques.

Ce module construit et maintient automatiquement un glossaire des traductions
de termes spécifiques pour garantir la cohérence tout au long du livre.
"""

import json
from pathlib import Path
from typing import Optional
from collections import defaultdict


class AutoGlossary:
    """
    Glossaire automatique qui apprend les traductions au fur et à mesure.

    Le glossaire suit les traductions de termes spécifiques (noms propres,
    termes techniques) et propose des traductions cohérentes basées sur
    l'historique.

    Example:
        >>> glossary = AutoGlossary()
        >>> glossary.learn("Matrix", "Matrice")
        >>> glossary.learn("Matrix", "Matrice")  # Renforce
        >>> glossary.learn("Matrix", "Système")   # Conflit !
        >>> glossary.get_translation("Matrix")
        'Matrice'  # La plus fréquente
    """

    def __init__(self, cache_path: Optional[Path] = None):
        """
        Initialise le glossaire.

        Args:
            cache_path: Chemin optionnel pour sauvegarder/charger le glossaire
        """
        self.cache_path = cache_path
        # {terme_source: {traduction: count}}
        self._glossary: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # {terme_source: traduction_validée}
        self._validated: dict[str, str] = {}

        if cache_path and cache_path.exists():
            self._load_from_cache()

    def learn(self, source_term: str, translated_term: str) -> None:
        """
        Enregistre une traduction observée.

        Args:
            source_term: Terme dans la langue source
            translated_term: Traduction observée
        """
        # Ignorer si identiques (ex: noms propres gardés tels quels)
        if source_term == translated_term:
            return

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
        """
        self._validated[source_term] = validated_translation

    def get_conflicts(self) -> dict[str, list[str]]:
        """
        Identifie les termes avec des traductions conflictuelles.

        Retourne les termes qui ont plusieurs traductions fréquentes
        (aucune ne domine à >70%).

        Returns:
            Dictionnaire {terme: [traductions_conflictuelles]}
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

    def to_dict(self) -> dict[str, str]:
        """
        Exporte le glossaire sous forme de dictionnaire simple.

        Returns:
            Dictionnaire {terme_source: traduction_recommandée}
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

    def save(self, path: Optional[Path] = None) -> None:
        """
        Sauvegarde le glossaire sur disque.

        Args:
            path: Chemin de sauvegarde (utilise cache_path si non fourni)
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

        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_from_cache(self) -> None:
        """Charge le glossaire depuis le cache."""
        if not self.cache_path or not self.cache_path.exists():
            return

        try:
            with open(self.cache_path, 'r', encoding='utf-8') as f:
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

    def get_stats(self) -> dict[str, int]:
        """
        Retourne des statistiques sur le glossaire.

        Returns:
            Dictionnaire avec les stats
        """
        return {
            "total_terms": len(self._glossary),
            "validated_terms": len(self._validated),
            "conflicting_terms": len(self.get_conflicts()),
            "unique_translations": sum(
                len(translations) for translations in self._glossary.values()
            ),
        }

    def __str__(self) -> str:
        """Représentation textuelle du glossaire."""
        stats = self.get_stats()
        return (
            f"AutoGlossary(\n"
            f"  termes: {stats['total_terms']}\n"
            f"  validés: {stats['validated_terms']}\n"
            f"  conflits: {stats['conflicting_terms']}\n"
            f")"
        )
