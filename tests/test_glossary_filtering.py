"""
Tests pour le système de filtrage du glossaire.

Ce module teste les fonctionnalités de nettoyage du glossaire :
- Détection et filtrage des stopwords grammaticaux
- Détection d'erreurs d'extraction
- Catégorisation des conflits terminologiques
- Méthodes de nettoyage (clean_stopwords, remove_low_confidence_terms, clean_all)
"""

import pytest
from pathlib import Path

from ebook_translator.glossary import Glossary
from ebook_translator.glossary_filters import (
    is_grammatical_stopword,
    should_exclude_from_glossary,
    is_likely_extraction_error,
    categorize_conflict,
    get_high_priority_conflicts,
    get_low_priority_conflicts,
)


class TestStopwordDetection:
    """Tests pour détection de stopwords."""

    def test_is_grammatical_stopword_articles(self):
        """Test : Détection d'articles."""
        assert is_grammatical_stopword("the")
        assert is_grammatical_stopword("a")
        assert is_grammatical_stopword("an")
        assert not is_grammatical_stopword("Matrix")

    def test_is_grammatical_stopword_pronouns(self):
        """Test : Détection de pronoms."""
        assert is_grammatical_stopword("he")
        assert is_grammatical_stopword("she")
        assert is_grammatical_stopword("they")
        assert is_grammatical_stopword("it")
        assert not is_grammatical_stopword("Sakamoto")

    def test_is_grammatical_stopword_prepositions(self):
        """Test : Détection de prépositions."""
        assert is_grammatical_stopword("in")
        assert is_grammatical_stopword("on")
        assert is_grammatical_stopword("after")
        assert is_grammatical_stopword("before")
        assert not is_grammatical_stopword("Association")

    def test_is_grammatical_stopword_case_insensitive(self):
        """Test : Détection insensible à la casse."""
        assert is_grammatical_stopword("The")
        assert is_grammatical_stopword("THE")
        assert is_grammatical_stopword("In")


class TestExclusionLogic:
    """Tests pour logique d'exclusion complète."""

    def test_should_exclude_stopwords(self):
        """Test : Exclusion des stopwords."""
        assert should_exclude_from_glossary("the")
        assert should_exclude_from_glossary("after")
        assert should_exclude_from_glossary("are")

    def test_should_exclude_single_letter(self):
        """Test : Exclusion lettres isolées."""
        assert should_exclude_from_glossary("a")
        assert should_exclude_from_glossary("I")
        assert not should_exclude_from_glossary("AA")  # Acronyme 2 lettres

    def test_should_exclude_two_letters_lowercase(self):
        """Test : Exclusion mots 2 lettres en minuscule."""
        assert should_exclude_from_glossary("am")
        assert should_exclude_from_glossary("is")
        assert should_exclude_from_glossary("at")
        # Mais pas les noms propres courts
        assert not should_exclude_from_glossary("Dr")
        assert not should_exclude_from_glossary("Mr")

    def test_should_not_exclude_proper_nouns(self):
        """Test : Préservation noms propres."""
        assert not should_exclude_from_glossary("Matrix")
        assert not should_exclude_from_glossary("Sakamoto")
        assert not should_exclude_from_glossary("Association")


class TestExtractionErrors:
    """Tests pour détection d'erreurs d'extraction."""

    def test_is_likely_extraction_error_grammatical_to_proper(self):
        """Test : Stopword source → nom propre traduit (erreur)."""
        # "after" → "Flio" est probablement une erreur
        assert is_likely_extraction_error("after", "Flio")
        assert is_likely_extraction_error("of", "Association")

    def test_is_likely_extraction_error_length_ratio(self):
        """Test : Différence de longueur excessive (ratio > 5)."""
        # "of" (2 chars) → "Association" (11 chars) = ratio 5.5
        assert is_likely_extraction_error("of", "Association")
        # "a" (1 char) → "Matrix" (6 chars) = ratio 6.0
        assert is_likely_extraction_error("a", "Matrix")

    def test_is_likely_extraction_error_legitimate(self):
        """Test : Traductions légitimes ne sont pas des erreurs."""
        assert not is_likely_extraction_error("Matrix", "Matrice")
        assert not is_likely_extraction_error("Association", "Guilde")
        assert not is_likely_extraction_error("Sakamoto", "Sakamoto")


class TestConflictCategorization:
    """Tests pour catégorisation des conflits."""

    def test_categorize_conflict_grammatical(self):
        """Test : Catégorie grammatical."""
        assert categorize_conflict("after", ["Après", "Au", "Flio"]) == "grammatical"
        assert categorize_conflict("are", ["Vous", "Il", "Nous"]) == "grammatical"

    def test_categorize_conflict_onomatopoeia(self):
        """Test : Catégorie onomatopée."""
        # <= 4 lettres + répétition de lettres (case-insensitive detection)
        assert categorize_conflict("Ahh", ["Ahh", "Aah"]) == "onomatopoeia"
        assert categorize_conflict("ooh", ["ooh", "ouh"]) == "onomatopoeia"
        assert categorize_conflict("pfft", ["pfft", "pff"]) == "onomatopoeia"
        # Note: Uppercase onomatopoeia like "Ooh" are categorized as proper_noun
        # because case matters in the repetition check

    def test_categorize_conflict_proper_noun(self):
        """Test : Catégorie nom propre."""
        # Toutes traductions commencent par majuscule
        assert (
            categorize_conflict("Association", ["Association", "Guilde"])
            == "proper_noun"
        )
        assert categorize_conflict("Matrix", ["Matrice", "Système"]) == "proper_noun"

    def test_categorize_conflict_contextual(self):
        """Test : Catégorie contextuel (défaut)."""
        # Commence par majuscule mais traductions mixtes
        assert categorize_conflict("Dark", ["Sombre", "noir"]) == "contextual"
        # Mot normal avec variations légitimes
        assert categorize_conflict("guild", ["guilde", "corporation"]) == "contextual"


class TestPriorityFiltering:
    """Tests pour filtrage par priorité."""

    def test_get_high_priority_conflicts(self):
        """Test : Extraction conflits haute priorité."""
        conflicts = {
            "after": ["Après", "Au"],  # grammatical → basse priorité
            "Association": ["Association", "Guilde"],  # proper_noun → haute priorité
            "Ahh": ["Ahh", "Aah"],  # onomatopoeia → basse priorité
            "Matrix": ["Matrice", "Système"],  # proper_noun → haute priorité
        }

        high_priority = get_high_priority_conflicts(conflicts)

        assert "Association" in high_priority
        assert "Matrix" in high_priority
        assert "after" not in high_priority
        assert "Ahh" not in high_priority

    def test_get_low_priority_conflicts(self):
        """Test : Extraction conflits basse priorité."""
        conflicts = {
            "after": ["Après", "Au"],  # grammatical → basse priorité
            "Association": ["Association", "Guilde"],  # proper_noun → haute priorité
            "Ahh": ["Ahh", "Aah"],  # onomatopoeia → basse priorité
        }

        low_priority = get_low_priority_conflicts(conflicts)

        assert "after" in low_priority
        assert "Ahh" in low_priority
        assert "Association" not in low_priority


class TestGlossaryLearnFiltering:
    """Tests pour filtrage automatique dans learn()."""

    def test_learn_filters_stopwords_automatically(self, tmp_path):
        """Test : learn() filtre automatiquement les stopwords."""
        glossary = Glossary(cache_path=tmp_path / "glossary.json")

        # Apprendre des stopwords (doivent être ignorés)
        glossary.learn("the", "le")
        glossary.learn("after", "Après")
        glossary.learn("are", "sont")

        # Vérifier qu'ils n'ont pas été ajoutés
        assert glossary.get_term_count() == 0

    def test_learn_accepts_proper_nouns(self, tmp_path):
        """Test : learn() accepte les noms propres."""
        glossary = Glossary(cache_path=tmp_path / "glossary.json")

        glossary.learn("Matrix", "Matrice")
        glossary.learn("Sakamoto", "Sakamoto")
        glossary.learn("Association", "Guilde")

        assert glossary.get_term_count() == 3
        assert glossary.get_translation("Matrix") == "Matrice"

    def test_learn_filters_short_words(self, tmp_path):
        """Test : learn() filtre mots très courts."""
        glossary = Glossary(cache_path=tmp_path / "glossary.json")

        # Mots courts (1-2 lettres en minuscule)
        glossary.learn("a", "un")
        glossary.learn("I", "je")
        glossary.learn("am", "suis")
        glossary.learn("is", "est")

        # Tous doivent être filtrés
        assert glossary.get_term_count() == 0

    def test_learn_accepts_short_proper_nouns(self, tmp_path):
        """Test : learn() accepte noms propres courts (majuscule)."""
        glossary = Glossary(cache_path=tmp_path / "glossary.json")

        glossary.learn("Dr", "Dr")
        glossary.learn("Mr", "M")

        # Doivent être acceptés (commencent par majuscule)
        assert glossary.get_term_count() == 2


class TestGlossaryCleanStopwords:
    """Tests pour clean_stopwords()."""

    def test_clean_stopwords_removes_grammatical_words(self, tmp_path):
        """Test : clean_stopwords() supprime mots grammaticaux."""
        glossary = Glossary(cache_path=tmp_path / "glossary.json")

        # Ajouter directement (bypass learn() filtering)
        glossary._glossary["the"]["le"] = 5
        glossary._glossary["after"]["Après"] = 3
        glossary._glossary["Matrix"]["Matrice"] = 10

        assert glossary.get_term_count() == 3

        removed = glossary.clean_stopwords()

        assert removed == 2  # "the" et "after" supprimés
        assert glossary.get_term_count() == 1
        assert "Matrix" in glossary._glossary
        assert "the" not in glossary._glossary
        assert "after" not in glossary._glossary

    def test_clean_stopwords_removes_from_validated(self, tmp_path):
        """Test : clean_stopwords() supprime aussi des validations."""
        glossary = Glossary(cache_path=tmp_path / "glossary.json")

        glossary._glossary["the"]["le"] = 5
        glossary._validated["the"] = "le"  # Validé manuellement

        removed = glossary.clean_stopwords()

        assert removed == 1
        assert "the" not in glossary._validated


class TestGlossaryRemoveLowConfidence:
    """Tests pour remove_low_confidence_terms()."""

    def test_remove_low_confidence_removes_single_occurrence(self, tmp_path):
        """Test : Suppression termes avec 1 seule occurrence."""
        glossary = Glossary(cache_path=tmp_path / "glossary.json")

        glossary._glossary["Matrix"]["Matrice"] = 10
        glossary._glossary["Rare"]["Rarissime"] = 1  # 1 occurrence → supprimé
        glossary._glossary["Another"]["Autre"] = 1  # 1 occurrence → supprimé

        assert glossary.get_term_count() == 3

        removed = glossary.remove_low_confidence_terms(min_occurrences=2)

        assert removed == 2
        assert glossary.get_term_count() == 1
        assert "Matrix" in glossary._glossary

    def test_remove_low_confidence_keeps_high_frequency(self, tmp_path):
        """Test : Préservation termes fréquents."""
        glossary = Glossary(cache_path=tmp_path / "glossary.json")

        glossary._glossary["Matrix"]["Matrice"] = 5
        glossary._glossary["Matrix"]["Système"] = 3  # Total = 8 → conservé

        removed = glossary.remove_low_confidence_terms(min_occurrences=2)

        assert removed == 0
        assert "Matrix" in glossary._glossary


class TestGlossaryCleanAll:
    """Tests pour clean_all()."""

    def test_clean_all_applies_both_filters(self, tmp_path):
        """Test : clean_all() applique stopwords + faible confiance."""
        glossary = Glossary(cache_path=tmp_path / "glossary.json")

        # Stopwords
        glossary._glossary["the"]["le"] = 5
        glossary._glossary["after"]["Après"] = 3

        # Faible confiance
        glossary._glossary["Rare"]["Rarissime"] = 1

        # Légitime
        glossary._glossary["Matrix"]["Matrice"] = 10

        assert glossary.get_term_count() == 4

        stats = glossary.clean_all(min_occurrences=2, verbose=False)

        assert stats["stopwords"] == 2
        assert stats["low_confidence"] == 1
        assert stats["total"] == 3
        assert glossary.get_term_count() == 1
        assert "Matrix" in glossary._glossary

    def test_clean_all_returns_stats(self, tmp_path):
        """Test : clean_all() retourne statistiques."""
        glossary = Glossary(cache_path=tmp_path / "glossary.json")

        glossary._glossary["the"]["le"] = 5
        glossary._glossary["Rare"]["Rarissime"] = 1

        stats = glossary.clean_all(min_occurrences=2, verbose=False)

        assert "stopwords" in stats
        assert "low_confidence" in stats
        assert "total" in stats
        assert stats["total"] == stats["stopwords"] + stats["low_confidence"]
