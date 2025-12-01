# Guide de Développement - ebook-translator

Ce guide détaille le processus de développement pour **ebook-translator**, avec des exemples concrets et des workflows recommandés.

## 📋 Table des matières

- [Setup environnement](#setup-environnement)
- [Processus de développement](#processus-de-développement)
- [Développement incrémental en pratique](#développement-incrémental-en-pratique)
- [Workflow quotidien](#workflow-quotidien)
- [Debugging et troubleshooting](#debugging-et-troubleshooting)
- [Bonnes pratiques](#bonnes-pratiques)

---

## ⚙️ Setup environnement

### Prérequis

- Python 3.12+
- Poetry (gestionnaire de dépendances)
- Git

### Installation complète

```bash
# 1. Cloner le dépôt
git clone https://github.com/NeOzay/ebook-translator.git
cd ebook-translator

# 2. Créer l'environnement virtuel avec Poetry
poetry install --with dev

# 3. Activer l'environnement (optionnel, Poetry gère automatiquement)
poetry shell

# 4. Configurer les variables d'environnement
cp .env.example .env
# Éditer .env et ajouter votre clé API DeepSeek
nano .env  # ou votre éditeur préféré
```

**Contenu minimal de `.env` :**

```bash
DEEPSEEK_API_KEY=sk-votre-cle-api-ici
DEEPSEEK_URL=https://api.deepseek.com  # Optionnel, valeur par défaut
```

### Installation des pre-commit hooks

Les pre-commit hooks exécutent automatiquement les vérifications de qualité avant chaque commit.

```bash
# Installer les hooks
poetry run pre-commit install

# Tester l'installation
poetry run pre-commit run --all-files
```

**Ce que font les pre-commit hooks :**

1. **Black** - Formate automatiquement le code
2. **Isort** - Trie et organise les imports
3. **Ruff** - Linting (détection d'erreurs de style/qualité)
4. **Pyright** - Vérification des types (mode strict)
5. **Hooks standards** - Trailing whitespace, fin de ligne, YAML/TOML valid, etc.

### Vérifier que tout fonctionne

```bash
# Tests unitaires
poetry run pytest
# Devrait afficher : "XX passed in X.XXs"

# Vérification des types
poetry run pyright src/
# Devrait afficher : "0 errors, 0 warnings"

# Pre-commit
poetry run pre-commit run --all-files
# Tous les hooks devraient être verts (Passed)
```

Si tous les tests passent, vous êtes prêt à développer ! 🚀

---

## 🔄 Processus de développement

### Étapes recommandées pour toute nouvelle feature

1. **Créer une issue** (optionnel mais recommandé)
   - Décrire la feature ou le bug
   - Obtenir un numéro d'issue (#123)

2. **Créer une branche**
   ```bash
   git checkout -b feature/ma-nouvelle-feature
   # Ou : bugfix/mon-bug, refactor/mon-refactoring, etc.
   ```

3. **Décomposer en sous-tâches** (pour features complexes)
   - Identifier les composants indépendants
   - Planifier l'ordre d'implémentation
   - Créer une checklist dans l'issue

4. **Développer de manière incrémentale**
   - Implémenter une sous-tâche à la fois
   - Tester chaque sous-tâche
   - Commit atomique après validation

5. **Créer une Pull Request**
   - Description claire des changements
   - Vérifier que tous les tests passent
   - Attendre la review

6. **Merge et cleanup**
   - Merger dans master après approbation
   - Supprimer la branche feature

---

## 🎯 Développement incrémental en pratique

### Exemple concret : Ajouter un nouveau check de validation

**Contexte :** Vous voulez ajouter un `QuotationMarkCheck` pour vérifier l'équilibre des guillemets dans les traductions.

#### Étape 1 : Planification

**Décomposition en sous-tâches :**

```markdown
Feature: QuotationMarkCheck - Validation des guillemets

Sous-tâches :
1. [ ] Créer la structure de base du check
2. [ ] Implémenter validate() - Détection des déséquilibres
3. [ ] Implémenter correct() - Correction automatique via LLM
4. [ ] Implémenter get_invalid_lines() - Filtrage des lignes
5. [ ] Intégrer au ValidationPipeline
6. [ ] Ajouter tests d'intégration
```

#### Étape 2 : Branche et sous-tâche 1

```bash
# Créer la branche feature
git checkout -b feature/quotation-mark-check

# Créer le fichier du check
touch src/ebook_translator/checks/check_tests/quotation_mark_check.py
```

**Implémenter la structure de base :**

```python
"""
Check de validation pour l'équilibre des guillemets dans les traductions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ebook_translator.checks.pipeline import ValidationContext
    from ebook_translator.checks.result import CheckResult


class QuotationMarkCheck:
    """
    Vérifie l'équilibre des guillemets dans les traductions.

    Ce check détecte les guillemets ouvrants/fermants déséquilibrés
    qui pourraient indiquer une traduction incomplète ou malformée.

    Example:
        >>> check = QuotationMarkCheck()
        >>> result = check.validate(context)
        >>> if not result.is_valid:
        ...     corrections = check.correct(context, result.error_data)
    """

    @property
    def name(self) -> str:
        """Nom du check pour logging et rapports."""
        return "QuotationMarkCheck"

    def validate(self, context: ValidationContext) -> CheckResult:
        """
        Valide l'équilibre des guillemets dans les traductions.

        Args:
            context: Contexte de validation avec textes originaux/traduits

        Returns:
            CheckResult avec is_valid=True si tous les guillemets sont équilibrés,
            sinon is_valid=False avec error_data contenant les lignes problématiques
        """
        # TODO: Implémenter la validation
        from ebook_translator.checks.result import CheckResult
        return CheckResult(is_valid=True, error_data={})

    def correct(
        self, context: ValidationContext, error_data: dict
    ) -> dict[int, str]:
        """
        Corrige les déséquilibres de guillemets via appel LLM.

        Args:
            context: Contexte de validation
            error_data: Données d'erreur de validate()

        Returns:
            Dictionnaire {line_number: corrected_text}
        """
        # TODO: Implémenter la correction
        return {}

    def get_invalid_lines(
        self, context: ValidationContext, error_data: dict
    ) -> set[int]:
        """
        Identifie les lignes à filtrer si correction impossible.

        Args:
            context: Contexte de validation
            error_data: Données d'erreur de validate()

        Returns:
            Set des numéros de ligne invalides
        """
        # TODO: Implémenter le filtrage
        return set()
```

**Créer le test initial :**

```bash
touch tests/test_quotation_mark_check.py
```

```python
"""Tests pour QuotationMarkCheck."""

import pytest
from unittest.mock import Mock

from ebook_translator.checks.check_tests.quotation_mark_check import QuotationMarkCheck
from ebook_translator.checks.pipeline import ValidationContext
from ebook_translator.segmentation.chunk import Chunk


class TestQuotationMarkCheck:
    """Tests pour la classe QuotationMarkCheck."""

    def test_check_name(self):
        """Vérifie que le nom du check est correct."""
        check = QuotationMarkCheck()
        assert check.name == "QuotationMarkCheck"

    def test_validate_structure_exists(self):
        """Vérifie que validate() existe et retourne CheckResult."""
        check = QuotationMarkCheck()

        # Context mock minimal
        context = ValidationContext(
            chunk=Chunk(index=0),
            translated_texts={0: "Test"},
            original_texts={0: "Test"},
            llm=Mock(),
            target_language="fr",
            phase="initial",
            max_retries=2,
            filtered_lines=[],
        )

        result = check.validate(context)
        assert hasattr(result, 'is_valid')
        assert hasattr(result, 'error_data')
```

**Valider la sous-tâche 1 :**

```bash
# Exécuter le test
poetry run pytest tests/test_quotation_mark_check.py -v

# Vérifier les types
poetry run pyright src/ebook_translator/checks/check_tests/quotation_mark_check.py

# Commit atomique
git add src/ebook_translator/checks/check_tests/quotation_mark_check.py tests/test_quotation_mark_check.py
git commit -m "feat: QuotationMarkCheck - Structure de base avec interfaces"
```

✅ **Sous-tâche 1 complétée !** Passons à la suivante.

#### Étape 3 : Sous-tâche 2 - Implémenter validate()

**Implémenter la logique de validation :**

```python
def validate(self, context: ValidationContext) -> CheckResult:
    """
    Valide l'équilibre des guillemets dans les traductions.

    Args:
        context: Contexte de validation avec textes originaux/traduits

    Returns:
        CheckResult avec is_valid=True si tous les guillemets sont équilibrés,
        sinon is_valid=False avec error_data contenant les lignes problématiques
    """
    from ebook_translator.checks.result import CheckResult

    errors: dict[int, dict[str, int]] = {}

    for line_num, translated_text in context.translated_texts.items():
        # Compter les guillemets ouvrants et fermants
        opening_quotes = translated_text.count('"') + translated_text.count('«')
        closing_quotes = translated_text.count('"') + translated_text.count('»')

        # Déséquilibre détecté
        if opening_quotes != closing_quotes:
            errors[line_num] = {
                "opening": opening_quotes,
                "closing": closing_quotes,
                "text": translated_text,
            }

    is_valid = len(errors) == 0

    return CheckResult(
        is_valid=is_valid,
        error_data={"unbalanced_lines": errors} if not is_valid else {}
    )
```

**Ajouter des tests complets :**

```python
class TestQuotationMarkCheck:
    # ... tests existants ...

    def test_validate_balanced_quotes(self):
        """Vérifie que les guillemets équilibrés passent la validation."""
        check = QuotationMarkCheck()

        context = ValidationContext(
            chunk=Chunk(index=0),
            translated_texts={
                0: "Il dit : « Bonjour ».",
                1: "Elle répondit : « Merci beaucoup ».",
            },
            original_texts={0: "Test", 1: "Test"},
            llm=Mock(),
            target_language="fr",
            phase="initial",
            max_retries=2,
            filtered_lines=[],
        )

        result = check.validate(context)
        assert result.is_valid is True
        assert result.error_data == {}

    def test_validate_unbalanced_quotes(self):
        """Vérifie que les guillemets déséquilibrés échouent la validation."""
        check = QuotationMarkCheck()

        context = ValidationContext(
            chunk=Chunk(index=0),
            translated_texts={
                0: "Il dit : « Bonjour.",  # Guillemet fermant manquant
                1: "Elle répondit : Merci ».",  # Guillemet ouvrant manquant
            },
            original_texts={0: "Test", 1: "Test"},
            llm=Mock(),
            target_language="fr",
            phase="initial",
            max_retries=2,
            filtered_lines=[],
        )

        result = check.validate(context)
        assert result.is_valid is False
        assert "unbalanced_lines" in result.error_data
        assert 0 in result.error_data["unbalanced_lines"]
        assert 1 in result.error_data["unbalanced_lines"]
```

**Valider la sous-tâche 2 :**

```bash
# Exécuter les tests
poetry run pytest tests/test_quotation_mark_check.py -v

# Vérifier les types
poetry run pyright src/ebook_translator/checks/check_tests/quotation_mark_check.py

# Commit atomique
git add src/ebook_translator/checks/check_tests/quotation_mark_check.py tests/test_quotation_mark_check.py
git commit -m "feat: QuotationMarkCheck - Implémentation validate() avec détection déséquilibres"
```

✅ **Sous-tâche 2 complétée !**

#### Étape 4 : Continuer de manière incrémentale

Répéter le même processus pour :
- Sous-tâche 3 : `correct()`
- Sous-tâche 4 : `get_invalid_lines()`
- Sous-tâche 5 : Intégration au `ValidationPipeline`
- Sous-tâche 6 : Tests d'intégration

**Chaque sous-tâche suit le même pattern :**

1. Implémenter la fonctionnalité
2. Écrire les tests
3. Valider (tests + types)
4. Commit atomique

#### Étape 5 : Créer la Pull Request

Une fois toutes les sous-tâches complétées :

```bash
# Vérifier que tout est OK
poetry run pytest                           # Tous les tests
poetry run pyright src/                     # Types stricts
poetry run pre-commit run --all-files       # Pre-commit hooks

# Pousser la branche
git push origin feature/quotation-mark-check

# Créer la PR sur GitHub avec template
```

---

## 🔧 Workflow quotidien

### Début de session de développement

```bash
# 1. Mettre à jour master
git checkout master
git pull origin master

# 2. Créer/continuer branche feature
git checkout -b feature/ma-feature
# Ou : git checkout feature/ma-feature (si existe déjà)

# 3. Activer l'environnement (si pas déjà fait)
poetry shell

# 4. Vérifier que l'environnement fonctionne
poetry run pytest
```

### Pendant le développement

```bash
# Exécuter les tests fréquemment
poetry run pytest tests/test_mon_module.py -v

# Vérifier les types
poetry run pyright src/ebook_translator/mon_module.py

# Formater automatiquement
poetry run black src/ebook_translator/mon_module.py
poetry run isort src/ebook_translator/mon_module.py

# Ou tout en une fois
poetry run pre-commit run --files src/ebook_translator/mon_module.py
```

### Avant de commit

```bash
# 1. Vérifier que tous les tests passent
poetry run pytest

# 2. Vérifier les types (strict mode)
poetry run pyright src/

# 3. Pre-commit hooks (automatique au commit, mais peut être manuel)
poetry run pre-commit run --all-files

# 4. Commit (les hooks se lancent automatiquement)
git add .
git commit -m "feat: Description de mon changement"

# 5. Si les hooks échouent, corriger et recommiter
# Les hooks peuvent auto-corriger certains problèmes (black, isort)
git add .  # Ajouter les corrections automatiques
git commit -m "feat: Description de mon changement"
```

### Fin de session / Avant PR

```bash
# 1. S'assurer que tout est à jour avec master
git checkout master
git pull origin master
git checkout feature/ma-feature
git rebase master  # Ou : git merge master

# 2. Résoudre les conflits si nécessaire

# 3. Vérifications finales
poetry run pytest                       # Tous les tests
poetry run pyright src/                 # Types stricts
poetry run pre-commit run --all-files   # Tous les hooks

# 4. Pousser et créer PR
git push origin feature/ma-feature
# Créer PR sur GitHub
```

---

## 🐛 Debugging et troubleshooting

### Tests qui échouent

```bash
# Exécuter un seul test avec verbose
poetry run pytest tests/test_module.py::TestClass::test_function -v

# Afficher les print() dans les tests
poetry run pytest tests/test_module.py -v -s

# Debugger avec pdb
poetry run pytest tests/test_module.py --pdb

# Coverage pour identifier code non testé
poetry run pytest --cov=src/ebook_translator --cov-report=html
# Ouvrir htmlcov/index.html dans un navigateur
```

### Erreurs de typage Pyright

```bash
# Vérifier un fichier spécifique
poetry run pyright src/ebook_translator/mon_module.py

# Mode verbose pour plus de détails
poetry run pyright src/ebook_translator/mon_module.py -v

# Ignorer temporairement une erreur (à utiliser avec parcimonie)
# Ajouter un commentaire dans le code :
result = function_without_types()  # type: ignore[no-untyped-call]  # TODO: Typer function_without_types
```

### Pre-commit hooks qui échouent

```bash
# Identifier quel hook échoue
poetry run pre-commit run --all-files

# Exécuter un hook spécifique
poetry run pre-commit run black --all-files
poetry run pre-commit run pyright --all-files

# Corriger automatiquement ce qui peut l'être
poetry run black src/ tests/
poetry run isort src/ tests/
poetry run ruff check --fix src/ tests/

# Re-essayer les hooks
poetry run pre-commit run --all-files
```

### Dépendances manquantes

```bash
# Réinstaller toutes les dépendances
poetry install --with dev

# Ajouter une nouvelle dépendance
poetry add nom-du-package

# Ajouter une dépendance de dev
poetry add --group dev nom-du-package

# Mettre à jour les dépendances
poetry update
```

---

## ✅ Bonnes pratiques

### 1. Commits atomiques

**Un commit = une préoccupation logique**

```bash
# ✅ BON : Commits séparés pour préoccupations distinctes
git commit -m "feat: QuotationMarkCheck - Structure de base"
git commit -m "feat: QuotationMarkCheck - Implémentation validate()"
git commit -m "test: QuotationMarkCheck - Tests unitaires complets"

# ❌ MAUVAIS : Tout en un seul commit
git commit -m "feat: QuotationMarkCheck - Tout implémenté + tests"
```

### 2. Tests avant implémentation (TDD optionnel)

Pour du code critique, envisagez le Test-Driven Development :

```python
# 1. Écrire le test d'abord (qui échoue)
def test_validate_unbalanced_quotes():
    # Test qui va échouer car validate() retourne toujours True
    ...

# 2. Implémenter juste assez pour que le test passe
def validate(self, context):
    # Implémentation minimale
    ...

# 3. Refactorer si nécessaire
```

### 3. Documentation au fil de l'eau

Ne pas attendre la fin pour documenter :

```python
# ✅ BON : Docstring écrite en même temps que la fonction
def validate(self, context: ValidationContext) -> CheckResult:
    """
    Valide l'équilibre des guillemets dans les traductions.

    Args:
        context: Contexte de validation

    Returns:
        CheckResult avec statut de validation
    """
    ...

# ❌ MAUVAIS : Code sans doc, "je documenterai plus tard"
def validate(self, context):
    ...
```

### 4. Review de son propre code

Avant de commit, relisez votre code :

```bash
# Voir les changements avant de commit
git diff

# Voir les changements ligne par ligne en mode interactif
git add -p

# Commit uniquement ce qui est pertinent
git add fichier1.py fichier2.py
git commit -m "feat: Description"
```

### 5. Breaks réguliers

Développer de manière incrémentale permet des breaks naturels :

- ✅ Sous-tâche 1 complétée → Break
- ✅ Tests passent → Break
- ✅ Commit → Break

### 6. Demander de l'aide

Si vous êtes bloqué :

1. Relire la documentation ([docs/](../))
2. Regarder des exemples dans le code existant
3. Ouvrir une issue avec le tag `question`
4. Demander une review même partielle

---

## 📚 Ressources complémentaires

- [CONTRIBUTING.md](../CONTRIBUTING.md) - Standards de contribution
- [CODING_STANDARDS.md](CODING_STANDARDS.md) - Référence technique des standards
- [ARCHITECTURE.md](ARCHITECTURE.md) - Architecture du projet
- [VALIDATION.md](VALIDATION.md) - Système de validation
- [TEMPLATES.md](TEMPLATES.md) - Architecture des templates

---

Bon développement ! 🚀
