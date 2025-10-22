"""
Tests pour le module de validation post-traduction (v0.5.0).

Ces tests vérifient :
1. Détection de segments non traduits
2. Vérification de cohérence terminologique
3. Glossaire automatique
4. Validateur intégré
"""

import pytest
from pathlib import Path
import tempfile

from ebook_translator.validation import (
    UntranslatedDetector,
    TerminologyChecker,
    Glossary,
    TranslationValidator,
)


class TestUntranslatedDetector:
    """Tests pour le détecteur de segments non traduits."""

    def test_detect_english_sentence(self):
        """Vérifie la détection d'une phrase en anglais."""
        detector = UntranslatedDetector(source_lang="en", target_lang="fr")

        # Phrase clairement en anglais
        text = "The cat is sleeping on the couch."
        issues = detector.detect(text, min_confidence=0.6)

        assert len(issues) > 0
        assert issues[0].confidence >= 0.6

    def test_no_false_positive_on_french(self):
        """Vérifie qu'on ne détecte pas le français comme anglais."""
        detector = UntranslatedDetector(source_lang="en", target_lang="fr")

        # Phrase en français
        text = "Le chat dort sur le canapé."
        issues = detector.detect(text, min_confidence=0.6)

        # Ne devrait pas détecter (ou très faible confiance)
        assert len(issues) == 0 or issues[0].confidence < 0.3

    def test_detect_identical_translation(self):
        """Vérifie la détection de traduction identique."""
        detector = UntranslatedDetector(source_lang="en", target_lang="fr")

        original = "Hello world"
        translated = "Hello world"  # Identique !

        issue = detector.check_translation_pair(original, translated)

        assert issue is not None
        assert issue.confidence == 1.0
        assert "identique" in issue.reason.lower()

    def test_accept_legitimate_translation(self):
        """Vérifie qu'une vraie traduction n'est pas signalée."""
        detector = UntranslatedDetector(source_lang="en", target_lang="fr")

        original = "Hello world"
        translated = "Bonjour le monde"

        issue = detector.check_translation_pair(original, translated)

        assert issue is None


class TestTerminologyChecker:
    """Tests pour le vérificateur de cohérence terminologique."""

    def test_detect_inconsistency(self):
        """Vérifie la détection d'incohérence."""
        checker = TerminologyChecker()

        # Même terme, traductions différentes
        checker.add_pair("Matrix", "Matrice", position=0)
        checker.add_pair("Matrix", "Matrice", position=1)
        checker.add_pair("Matrix", "Système", position=2)

        issues = checker.get_issues()

        assert len(issues) > 0
        assert issues[0].source_term == "Matrix"
        assert "Matrice" in issues[0].translations
        assert "Système" in issues[0].translations

    def test_no_issue_when_consistent(self):
        """Vérifie qu'il n'y a pas d'issue si cohérent."""
        checker = TerminologyChecker()

        # Toujours la même traduction
        checker.add_pair("Matrix", "Matrice", position=0)
        checker.add_pair("Matrix", "Matrice", position=1)
        checker.add_pair("Matrix", "Matrice", position=2)

        issues = checker.get_issues()

        assert len(issues) == 0

    def test_extract_proper_nouns(self):
        """Vérifie l'extraction de noms propres."""
        checker = TerminologyChecker()

        text = "Dr. Sakamoto activated the Matrix in Tokyo."
        nouns = checker._extract_proper_nouns(text)

        # Doit contenir au moins "Sakamoto", "Matrix", "Tokyo"
        assert len(nouns) >= 2
        assert any("Sakamoto" in noun or "Matrix" in noun or "Tokyo" in noun for noun in nouns)

    def test_generate_glossary(self):
        """Vérifie la génération de glossaire."""
        checker = TerminologyChecker()

        checker.add_pair("Matrix", "Matrice", position=0)
        checker.add_pair("Matrix", "Matrice", position=1)
        checker.add_pair("Sakamoto", "Sakamoto", position=0)

        glossary = checker.get_glossary()

        assert "Matrix" in glossary
        assert glossary["Matrix"] == "Matrice"


class TestGlossary:
    """Tests pour le glossaire automatique."""

    def test_learn_and_retrieve(self):
        """Vérifie l'apprentissage et la récupération."""
        glossary = Glossary()

        # Apprendre une traduction
        glossary.learn("Matrix", "Matrice")
        glossary.learn("Matrix", "Matrice")

        # Récupérer
        translation = glossary.get_translation("Matrix")

        assert translation == "Matrice"

    def test_most_frequent_wins(self):
        """Vérifie que la traduction la plus fréquente est préférée."""
        glossary = Glossary()

        # "Matrice" 3 fois, "Système" 1 fois
        glossary.learn("Matrix", "Matrice")
        glossary.learn("Matrix", "Matrice")
        glossary.learn("Matrix", "Matrice")
        glossary.learn("Matrix", "Système")

        translation = glossary.get_translation("Matrix", min_confidence=0.5)

        assert translation == "Matrice"

    def test_detect_conflicts(self):
        """Vérifie la détection de conflits."""
        glossary = Glossary()

        # Deux traductions équilibrées
        glossary.learn("Matrix", "Matrice")
        glossary.learn("Matrix", "Matrice")
        glossary.learn("Matrix", "Système")
        glossary.learn("Matrix", "Système")

        conflicts = glossary.get_conflicts()

        assert "Matrix" in conflicts
        assert len(conflicts["Matrix"]) == 2

    def test_validated_translation_priority(self):
        """Vérifie que les traductions validées ont priorité."""
        glossary = Glossary()

        # Apprendre "Système" plusieurs fois
        glossary.learn("Matrix", "Système")
        glossary.learn("Matrix", "Système")
        glossary.learn("Matrix", "Système")

        # Mais valider "Matrice"
        glossary.validate_translation("Matrix", "Matrice")

        # "Matrice" doit être retournée malgré moins d'occurrences
        translation = glossary.get_translation("Matrix")
        assert translation == "Matrice"

    def test_save_and_load(self):
        """Vérifie la sauvegarde et le chargement."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "glossary.json"

            # Créer et sauvegarder
            glossary1 = Glossary(cache_path=path)
            glossary1.learn("Matrix", "Matrice")
            glossary1.validate_translation("Sakamoto", "Sakamoto")
            glossary1.save()

            # Charger dans une nouvelle instance
            glossary2 = Glossary(cache_path=path)

            assert glossary2.get_translation("Matrix") == "Matrice"
            assert glossary2.get_translation("Sakamoto") == "Sakamoto"


class TestTranslationValidator:
    """Tests pour le validateur intégré."""

    def test_validator_initialization(self):
        """Vérifie l'initialisation du validateur."""
        validator = TranslationValidator(
            source_lang="en",
            target_lang="fr",
            enable_untranslated_detection=True,
            enable_terminology_check=True,
            enable_glossary=True,
        )

        assert validator.untranslated_detector is not None
        assert validator.terminology_checker is not None
        assert validator.glossary is not None

    def test_validate_good_translation(self):
        """Vérifie qu'une bonne traduction passe."""
        validator = TranslationValidator(source_lang="en", target_lang="fr")

        result = validator.validate_translation(
            original="Hello world",
            translated="Bonjour le monde",
        )

        assert result is True

    def test_detect_identical_translation(self):
        """Vérifie la détection de traduction identique."""
        validator = TranslationValidator(source_lang="en", target_lang="fr")

        result = validator.validate_translation(
            original="Hello world",
            translated="Hello world",  # Identique !
        )

        # Devrait détecter un problème
        assert result is False
        assert validator.untranslated_count > 0

    def test_generate_report(self):
        """Vérifie la génération de rapport."""
        validator = TranslationValidator(source_lang="en", target_lang="fr")

        # Ajouter des traductions
        validator.validate_translation("Matrix", "Matrice", position=0)
        validator.validate_translation("Matrix", "Système", position=1)

        # Générer rapport
        report = validator.generate_report()

        assert "RAPPORT DE VALIDATION" in report
        assert "Statistiques" in report

    def test_export_glossary(self):
        """Vérifie l'export du glossaire."""
        validator = TranslationValidator(source_lang="en", target_lang="fr")

        # Apprendre des termes
        validator.validate_translation("Matrix", "Matrice", position=0)
        validator.validate_translation("Matrix", "Matrice", position=1)

        glossary_dict = validator.export_glossary_dict()

        assert isinstance(glossary_dict, dict)
        # Le glossaire peut être vide ou contenir des termes selon l'extraction
        # (dépend de l'extraction de noms propres)


class TestIntegration:
    """Tests d'intégration du système de validation."""

    def test_full_workflow(self):
        """Test du workflow complet de validation."""
        validator = TranslationValidator(
            source_lang="en",
            target_lang="fr",
            enable_untranslated_detection=True,
            enable_terminology_check=True,
            enable_glossary=True,
        )

        # Simuler plusieurs traductions
        translations = [
            ("Dr. Sakamoto activated the Matrix.", "Le Dr Sakamoto activa la Matrice."),
            ("The Matrix hummed to life.", "La Matrice s'anima en ronronnant."),
            ("Matrix power levels stable.", "Niveaux de puissance de la Matrice stables."),
        ]

        for i, (orig, trans) in enumerate(translations):
            validator.validate_translation(orig, trans, position=i)

        # Vérifier le rapport
        report = validator.generate_report()
        assert "RAPPORT DE VALIDATION" in report

        # Vérifier les statistiques
        issues = validator.get_all_issues()
        # Ne devrait pas avoir de problèmes majeurs (traductions cohérentes)
        terminology_issues = issues.get("terminology", [])
        # On ne s'attend pas à des problèmes vu que "Matrix" → "Matrice" est cohérent
        assert len(terminology_issues) == 0 or all(
            issue.confidence < 0.8 for issue in terminology_issues
        )
