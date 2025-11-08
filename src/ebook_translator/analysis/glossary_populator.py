"""
Peupleur automatique de glossaire depuis l'analyse littéraire.

Ce module extrait les termes importants des fiches d'analyse (Phase 0)
et les injecte dans le glossaire de traduction pour pré-configurer
les termes techniques, noms propres et éléments spécialisés.

Avantages:
- Cohérence terminologique dès Phase 1 (vs apprentissage progressif)
- Réduction des conflits de traduction (traductions validées dès le début)
- Meilleure qualité globale (LLM connaît les termes importants)

Sources de termes:
- terminology.specialized_terms: Termes techniques avec catégories
- terminology.proper_nouns: Noms propres (personnes, lieux, organisations)
- characters.present[].name: Noms de personnages
- locations.primary/secondary: Noms de lieux

Stratégie d'injection:
- Termes techniques: Marquer comme "à traduire" (confidence=1.0)
- Noms propres: Marquer comme "préserver tel quel" (confidence=1.0)
- Validation manuelle recommandée après population automatique
"""

import logging
from typing import TYPE_CHECKING

from .schema import ChapterAnalysis

if TYPE_CHECKING:
    from ..glossary import Glossary


logger = logging.getLogger(__name__)


class GlossaryPopulator:
    """
    Peuple automatiquement le glossaire depuis les analyses littéraires.

    Cette classe extrait les termes importants (noms propres, terminologie technique)
    des fiches d'analyse JSON et les injecte dans le glossaire de traduction.

    Args:
        glossary: Instance du glossaire à peupler

    Example:
        >>> from ebook_translator.glossary import Glossary
        >>> glossary = Glossary(Path("cache/glossary.json"))
        >>> populator = GlossaryPopulator(glossary)
        >>> # Peupler depuis analyses multiples
        >>> populator.populate_from_analyses(analyses)
        >>> # Ou depuis une seule analyse
        >>> populator.populate_from_analysis("Chapter 1", analysis)
    """

    def __init__(self, glossary: "Glossary"):
        """
        Initialise le populator avec une instance de glossaire.

        Args:
            glossary: Glossaire à peupler
        """
        self.glossary = glossary
        self._extracted_terms: set[str] = set()  # Pour dédupliquer
        self._stats = {
            "characters": 0,
            "locations": 0,
            "specialized_terms": 0,
            "proper_nouns": 0,
        }

    def populate_from_analysis(
        self,
        chapter_name: str,
        analysis: ChapterAnalysis,
    ) -> None:
        """
        Peuple le glossaire depuis une analyse de chapitre.

        Extrait et injecte les termes dans l'ordre suivant:
        1. Noms de personnages (characters.present[].name)
        2. Noms de lieux (locations.primary/secondary)
        3. Noms propres génériques (terminology.proper_nouns)
        4. Termes spécialisés (terminology.specialized_terms)

        Args:
            chapter_name: Nom du chapitre (pour logging uniquement)
            analysis: Analyse littéraire structurée

        Example:
            >>> populator.populate_from_analysis("Chapter 1", analysis_dict)
            Extracted from 'Chapter 1': 5 characters, 3 locations, 12 specialized terms
        """
        logger.info(f"Extraction termes depuis '{chapter_name}'...")

        # 1. Extraire noms de personnages
        for character in analysis.get("characters", {}).get("present", []):
            name = character.get("name", "").strip()
            if name and name not in self._extracted_terms:
                # Noms propres: garder tels quels (traduction = source)
                # Note: Le glossaire ignore les termes identiques, donc on
                # devra utiliser validate() après pour forcer l'apprentissage
                self.glossary.learn(name, name)
                self._extracted_terms.add(name)
                self._stats["characters"] += 1

        # 2. Extraire noms de lieux
        locations_data = analysis.get("locations", {})

        # Lieu primaire
        primary_loc = locations_data.get("primary", {})
        if primary_loc and isinstance(primary_loc, dict):
            loc_name = primary_loc.get("name", "").strip()
            if loc_name and loc_name not in self._extracted_terms:
                self.glossary.learn(loc_name, loc_name)
                self._extracted_terms.add(loc_name)
                self._stats["locations"] += 1

        # Lieux secondaires
        for secondary_loc in locations_data.get("secondary", []):
            if isinstance(secondary_loc, dict):
                loc_name = secondary_loc.get("name", "").strip()
            elif isinstance(secondary_loc, str):
                loc_name = secondary_loc.strip()
            else:
                loc_name = ""

            if loc_name and loc_name not in self._extracted_terms:
                self.glossary.learn(loc_name, loc_name)
                self._extracted_terms.add(loc_name)
                self._stats["locations"] += 1

        # 3. Extraire noms propres génériques
        terminology = analysis.get("terminology", {})
        proper_nouns = terminology.get("proper_nouns", {})

        for category in ["names", "places", "organizations"]:
            for noun in proper_nouns.get(category, []):
                noun_str = noun.strip()
                if noun_str and noun_str not in self._extracted_terms:
                    self.glossary.learn(noun_str, noun_str)
                    self._extracted_terms.add(noun_str)
                    self._stats["proper_nouns"] += 1

        # 4. Extraire termes spécialisés
        # Note: Pour l'instant, on garde seulement le terme source tel quel
        # Dans une version avancée, on pourrait demander au LLM de suggérer
        # des traductions pour ces termes
        for term_entry in terminology.get("specialized_terms", []):
            term = term_entry.get("term", "").strip()
            if term and term not in self._extracted_terms:
                # Garder tel quel pour l'instant
                # TODO: Optionnel - demander traduction au LLM
                self.glossary.learn(term, term)
                self._extracted_terms.add(term)
                self._stats["specialized_terms"] += 1

        logger.info(
            f"Extrait de '{chapter_name}': "
            f"{self._stats['characters']} personnages, "
            f"{self._stats['locations']} lieux, "
            f"{self._stats['proper_nouns']} noms propres, "
            f"{self._stats['specialized_terms']} termes techniques"
        )

    def populate_from_analyses(
        self,
        analyses: dict[str, ChapterAnalysis],
    ) -> None:
        """
        Peuple le glossaire depuis plusieurs analyses de chapitres.

        Itère sur tous les chapitres et extrait les termes de chacun.

        Args:
            analyses: Dictionnaire {chapter_name: ChapterAnalysis}

        Example:
            >>> analyses = phase.run()  # Retourne dict[str, ChapterAnalysis]
            >>> populator.populate_from_analyses(analyses)
            Extracted from 'Prologue': ...
            Extracted from 'Chapter 1': ...
            ...
            Total extracted: 45 terms across 3 chapters
        """
        logger.info(f"Peuplement glossaire depuis {len(analyses)} chapitres...")

        for chapter_name, analysis in analyses.items():
            self.populate_from_analysis(chapter_name, analysis)

        logger.info(
            f"Peuplement terminé: "
            f"{sum(self._stats.values())} termes extraits "
            f"(personnages={self._stats['characters']}, "
            f"lieux={self._stats['locations']}, "
            f"noms_propres={self._stats['proper_nouns']}, "
            f"techniques={self._stats['specialized_terms']})"
        )

    def validate_all_terms(self) -> None:
        """
        Valide tous les termes extraits dans le glossaire.

        Appelle glossary.validate() pour chaque terme extrait afin de
        forcer l'apprentissage (bypass du filtre "terme identique").

        Note: Le glossaire ignore normalement les paires source=traduction
        identiques, mais pour les noms propres on veut les garder pour
        assurer la cohérence.

        Example:
            >>> populator.populate_from_analyses(analyses)
            >>> populator.validate_all_terms()
            Validated 45 terms in glossary
        """
        validated_count = 0

        for term in self._extracted_terms:
            # Forcer la validation (confidence=1.0)
            self.glossary.validate(term, term)
            validated_count += 1

        logger.info(f"Validé {validated_count} termes dans le glossaire")

    def get_stats(self) -> dict[str, int]:
        """
        Retourne les statistiques d'extraction.

        Returns:
            Dictionnaire avec compteurs par catégorie

        Example:
            >>> stats = populator.get_stats()
            >>> print(f"Personnages: {stats['characters']}")
        """
        return self._stats.copy()
