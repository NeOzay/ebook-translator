# Guide de Contribution - ebook-translator

Merci de votre intérêt pour contribuer à **ebook-translator** ! Ce guide décrit les standards et processus de développement du projet.

## 📋 Table des matières

- [Code de conduite](#code-de-conduite)
- [Standards de code](#standards-de-code)
- [Développement incrémental](#développement-incrémental)
- [Workflow Git](#workflow-git)
- [Configuration de l'environnement](#configuration-de-lenvironnement)
- [Checklist avant PR](#checklist-avant-pr)

---

## 🤝 Code de conduite

### Principes fondamentaux

1. **Qualité avant rapidité** - Mieux vaut prendre le temps de bien faire
2. **Tests systématiques** - Tout nouveau code doit être testé
3. **Documentation claire** - Le code doit être compréhensible par d'autres
4. **Rétrocompatibilité** - Éviter les breaking changes sans justification majeure

---

## 💻 Standards de code

### 1. Typage strict (OBLIGATOIRE)

**Tous les paramètres et retours de fonction doivent être typés.**

```python
# ✅ BON : Typage complet
def translate_chunk(
    chunk: Chunk,
    target_language: str,
    llm: LLM,
    max_retries: int = 3
) -> dict[int, str]:
    """Traduit un chunk avec typage strict."""
    result: dict[int, str] = {}
    return result

# ❌ MAUVAIS : Pas de typage
def translate_chunk(chunk, target_language, llm, max_retries=3):
    result = {}
    return result
```

**Variables complexes doivent être typées explicitement.**

```python
# ✅ BON : Typage explicite
translations: dict[int, str] = {}
error_lines: set[int] = set()
chunks: list[Chunk] = []

# ❌ MAUVAIS : Type implicite (ambiguë)
translations = {}
error_lines = set()
chunks = []
```

**Utiliser TypeAlias pour types réutilisés.**

```python
# ✅ BON : Type alias pour clarté
from typing import TypeAlias

GlossaryEntry: TypeAlias = dict[str, int]
GlossaryData: TypeAlias = dict[str, GlossaryEntry]

def load_glossary() -> GlossaryData:
    ...

# ❌ MAUVAIS : Type complexe répété
def load_glossary() -> dict[str, dict[str, int]]:
    ...
```

**Configuration basedpyright : Mode strict activé**

Le projet utilise basedpyright en mode strict. Toutes les erreurs de typage doivent être corrigées.

```bash
# Vérifier les types
uv run basedpyright src/

# Ne devrait retourner AUCUNE erreur
```

### 2. Documentation (OBLIGATOIRE)

**Toutes les docstrings doivent utiliser le format Google (OBLIGATOIRE pour toutes les fonctions/classes publiques).**

**⚠️ IMPORTANT** : Le format Google est le **seul format autorisé** pour les docstrings dans ce projet. Aucun autre format (reStructuredText, NumPy, etc.) n'est accepté.

```python
def validate_translation(
    original: dict[int, str],
    translated: dict[int, str],
    checks: list[Check]
) -> ValidationResult:
    """
    Valide une traduction selon une liste de checks.

    Cette fonction exécute tous les checks de validation sur une traduction
    et retourne un résultat agrégé avec les erreurs détectées.

    Args:
        original: Textes originaux indexés par numéro de ligne
        translated: Textes traduits indexés par numéro de ligne
        checks: Liste des checks de validation à exécuter

    Returns:
        ValidationResult contenant le statut et les erreurs détectées

    Raises:
        ValueError: Si les dictionnaires original/translated ont des clés différentes

    Example:
        >>> result = validate_translation(
        ...     original={0: "Hello"},
        ...     translated={0: "Bonjour"},
        ...     checks=[LineCountCheck()]
        ... )
        >>> assert result.is_valid
    """
    ...
```

**Sections obligatoires du format Google :**

- `Args:` - Paramètres de la fonction
- `Returns:` - Valeur de retour
- `Raises:` - Exceptions levées
- `Example:` - Exemple d'utilisation (optionnel mais recommandé)
- `Note:` - Notes importantes (optionnel)

### 3. Style et formatage (OBLIGATOIRE)

**Outils automatiques configurés :**

- **Black** : Formatage automatique (88 caractères/ligne)
- **Isort** : Tri et organisation des imports
- **Ruff** : Linting moderne (remplace flake8/pylint)

```bash
# Formater automatiquement le code
uv run black src/ tests/

# Trier les imports
uv run isort src/ tests/

# Linting
uv run ruff check src/ tests/

# Tout en une fois via pre-commit
uv run pre-commit run --all-files
```

**Conventions de nommage :**

```python
# Variables et fonctions : snake_case
chunk_index = 0
translated_text = ""

def get_translation() -> str:
    ...

# Classes : PascalCase
class ValidationWorker:
    ...

# Constantes : UPPER_SNAKE_CASE
MAX_RETRIES = 3
DEFAULT_OVERLAP_RATIO = 0.15

# Variables privées : _prefix
class MyClass:
    def __init__(self):
        self._internal_cache = {}
```

### 4. Gestion d'erreurs (OBLIGATOIRE)

**Exceptions spécifiques avec messages clairs.**

```python
# ✅ BON : Exception spécifique avec contexte
if not translated_texts:
    raise ValueError(
        f"Aucune traduction trouvée pour le chunk {chunk.index}. "
        f"💡 Vérifiez que le LLM a bien retourné des traductions."
    )

# ❌ MAUVAIS : Exception générique
if not translated_texts:
    raise Exception("Error")
```

**Logging structuré (pas de print()).**

```python
import logging

logger = logging.getLogger(__name__)

# ✅ BON : Logging avec niveaux appropriés
logger.info(f"Traduction du chunk {chunk.index} réussie")
logger.warning(f"Retry nécessaire pour chunk {chunk.index} (tentative {attempt})")
logger.error(f"Échec définitif chunk {chunk.index}: {error}")

# ❌ MAUVAIS : Utiliser print()
print(f"Traduction du chunk {chunk.index} réussie")
```

---

## 🔄 Développement incrémental

### Principe : Features complexes = sous-tâches + tests

**Pour toute feature complexe, suivez ce processus :**

1. **Décomposer** la feature en sous-tâches testables
2. **Implémenter** une sous-tâche à la fois
3. **Tester** chaque sous-tâche avant d'avancer
4. **Valider** que tout fonctionne ensemble
5. **Commit atomique** pour chaque sous-tâche complétée

### Exemple : Ajout d'un nouveau check de validation

**Feature complexe** : Ajouter un `QuotationMarkCheck` pour vérifier l'équilibre des guillemets.

**Décomposition en sous-tâches :**

```markdown
1. Créer la structure de base du check
   - [ ] Créer `checks/check_tests/quotation_mark_check.py`
   - [ ] Implémenter `validate()` (version simple)
   - [ ] Test unitaire : détection guillemets déséquilibrés

2. Implémenter la correction automatique
   - [ ] Implémenter `correct()` avec appel LLM
   - [ ] Test unitaire : correction guillemets manquants

3. Implémenter le filtrage des lignes invalides
   - [ ] Implémenter `get_invalid_lines()`
   - [ ] Test unitaire : identification lignes à filtrer

4. Intégration au pipeline
   - [ ] Ajouter QuotationMarkCheck à ValidationPipeline
   - [ ] Test d'intégration : pipeline complet avec nouveau check
```

**Workflow de développement :**

```bash
# Étape 1 : Structure de base
# 1. Créer le fichier
touch src/ebook_translator/checks/check_tests/quotation_mark_check.py

# 2. Implémenter validate() (version minimale)
# ... code ...

# 3. Écrire le test
touch tests/test_quotation_mark_check.py
# ... test ...

# 4. Valider que ça fonctionne
uv run pytest tests/test_quotation_mark_check.py -v

# 5. Commit atomique
git add src/ebook_translator/checks/check_tests/quotation_mark_check.py tests/test_quotation_mark_check.py
git commit -m "feat: QuotationMarkCheck - Structure de base avec validate()"

# Étape 2 : Correction automatique
# ... répéter le processus pour correct() ...

# Étape 3 : Filtrage
# ... répéter le processus pour get_invalid_lines() ...

# Étape 4 : Intégration
# ... tests d'intégration ...
git commit -m "feat: QuotationMarkCheck - Intégration au ValidationPipeline"
```

### Pourquoi le développement incrémental ?

✅ **Détection précoce des bugs** - Problèmes identifiés immédiatement
✅ **Code testable** - Chaque partie est testée indépendamment
✅ **Review facilitée** - PRs plus petites et focalisées
✅ **Rollback facile** - En cas de problème, on sait exactement où
✅ **Confiance** - Chaque étape validée avant d'avancer

---

## 🌳 Workflow Git

### Branches

**Convention de nommage :**

```bash
# Features
feature/description-courte
feature/phase0-literary-analysis
feature/glossary-export

# Bugfixes
bugfix/description-du-bug
bugfix/chunk-overlap-negative

# Refactoring
refactor/description
refactor/template-dry-architecture

# Documentation
docs/description
docs/contributing-guide
```

**Sous-branches pour features complexes :**

```bash
# Feature principale
feature/advanced-context

# Sous-branches
feature/advanced-context/metadata-extraction
feature/advanced-context/semantic-cache
feature/advanced-context/integration-tests

# Merge progressif : sous-branches → feature → master
```

### Commits conventionnels

**Format : `type: description`**

```bash
# Types de commits
feat:      # Nouvelle fonctionnalité
fix:       # Correction de bug
refactor:  # Refactoring sans changement de comportement
test:      # Ajout/modification de tests
docs:      # Documentation uniquement
chore:     # Tâches de maintenance (deps, config, etc.)
perf:      # Amélioration de performance
style:     # Formatage, whitespace (pas de changement logique)
```

**Exemples de bons messages :**

```bash
feat: QuotationMarkCheck - Validation et correction des guillemets

fix: Chunk overlap négatif quand max_tokens < overlap_tokens

refactor: Templates - Architecture DRY avec bases communes (-73% duplication)

test: ValidationPipeline - Tests d'intégration pour retry progressif

docs: CONTRIBUTING - Guide de développement incrémental

chore: pyproject.toml - Configuration basedpyright mode strict
```

**Messages descriptifs et concis :**

```bash
# ✅ BON : Décrit ce qui est fait et pourquoi
feat: Retry progressif avec mode reasoning pour corrections complexes

# ❌ MAUVAIS : Trop vague
feat: Amélioration validation

# ❌ MAUVAIS : Trop long et technique
feat: Ajout d'un système de retry à deux niveaux avec utilisation du mode reasoning de deepseek-reasoner pour les cas complexes qui nécessitent une analyse approfondie et une correction structurée avec logging détaillé et métriques de performance
```

### Pull Requests

**Avant de créer une PR :**

1. ✅ Tous les tests passent (`uv run pytest`)
2. ✅ basedpyright mode strict sans erreurs (`uv run basedpyright src/`)
3. ✅ Pre-commit hooks passent (`uv run pre-commit run --all-files`)
4. ✅ Code formaté (black + isort)
5. ✅ Coverage ≥ 80% pour nouveau code
6. ✅ Documentation à jour (docstrings, CHANGELOG.md si applicable)

**Description de PR :**

```markdown
## Description

[Description concise de ce que fait la PR]

## Type de changement

- [ ] Nouvelle fonctionnalité (feat)
- [ ] Correction de bug (fix)
- [ ] Refactoring (refactor)
- [ ] Documentation (docs)
- [ ] Tests (test)
- [ ] Autre (préciser) : _______

## Changements détaillés

- [Liste des changements principaux]
- [Fichiers modifiés importants]

## Tests

- [ ] Tests unitaires ajoutés/mis à jour
- [ ] Tests d'intégration ajoutés (si applicable)
- [ ] Tous les tests passent
- [ ] Coverage ≥ 80%

## Checklist qualité

- [ ] Code typé (basedpyright strict OK)
- [ ] Docstrings à jour
- [ ] Pre-commit hooks OK
- [ ] Pas de breaking changes (ou documentés)

## Références

Closes #[numéro issue] (si applicable)
```

---

## ⚙️ Configuration de l'environnement

### Installation initiale

```bash
# 1. Cloner le dépôt
git clone https://github.com/NeOzay/ebook-translator.git
cd ebook-translator

# 2. Installer les dépendances (avec dev)
uv sync --group dev

# 3. Copier et configurer .env
cp .env.example .env
# Éditer .env et ajouter votre clé API DeepSeek

# 4. Installer pre-commit hooks
uv run pre-commit install

# 5. Vérifier que tout fonctionne
uv run pytest
uv run basedpyright src/
uv run pre-commit run --all-files
```

### Outils de développement

**Vérifications manuelles :**

```bash
# Tests
uv run pytest                                    # Tous les tests
uv run pytest tests/test_specific.py -v         # Test spécifique
uv run pytest --cov=src/ebook_translator        # Avec coverage

# Type checking
uv run basedpyright src/                             # Mode strict

# Formatage et linting
uv run black src/ tests/                        # Formatage
uv run isort src/ tests/                        # Tri imports
uv run ruff check src/ tests/                   # Linting
uv run ruff check --fix src/ tests/             # Auto-fix

# Pre-commit (tout en une fois)
uv run pre-commit run --all-files               # Tous les fichiers
uv run pre-commit run --files src/module.py     # Fichier spécifique
```

**Configuration VSCode (recommandée) :**

Créer `.vscode/settings.json` :

```json
{
  "python.defaultInterpreterPath": ".venv/bin/python",
  "python.formatting.provider": "black",
  "python.linting.enabled": true,
  "python.linting.ruffEnabled": true,
  "python.analysis.typeCheckingMode": "strict",
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.organizeImports": true
  }
}
```

---

## ✅ Checklist avant PR

**Utilisez cette checklist avant de soumettre votre PR :**

### Code

- [ ] Tous les paramètres de fonction sont typés
- [ ] Tous les retours de fonction sont typés
- [ ] Variables complexes explicitement typées
- [ ] basedpyright strict sans erreurs (`uv run basedpyright src/`)
- [ ] Code formaté avec black (`uv run black src/ tests/`)
- [ ] Imports triés avec isort (`uv run isort src/ tests/`)
- [ ] Ruff linting OK (`uv run ruff check src/ tests/`)

### Documentation

- [ ] Docstrings ajoutées pour nouvelles fonctions/classes publiques
- [ ] Format Google UNIQUEMENT (Args, Returns, Raises, Example) - aucun autre format accepté
- [ ] CHANGELOG.md mis à jour (si version bump)
- [ ] README.md mis à jour (si nouvelle feature majeure)

### Tests

- [ ] Tests unitaires pour nouveau code
- [ ] Tests d'intégration pour features multi-composants
- [ ] Tous les tests passent (`uv run pytest`)
- [ ] Coverage ≥ 80% (`uv run pytest --cov`)
- [ ] Tests suivent le développement incrémental (une sous-tâche = un test)

### Git

- [ ] Commits conventionnels (feat:, fix:, etc.)
- [ ] Messages de commit descriptifs
- [ ] Branche nommée correctement (feature/, bugfix/, etc.)
- [ ] Pas de conflits avec master
- [ ] Pre-commit hooks OK (`uv run pre-commit run --all-files`)

### Qualité

- [ ] Pas de breaking changes (ou documentés et justifiés)
- [ ] Logging structuré (pas de print())
- [ ] Exceptions spécifiques avec messages clairs
- [ ] Code suit les principes SOLID
- [ ] Pas de code commenté inutilement

---

## 📚 Ressources

- [Documentation complète](docs/)
- [Guide de développement détaillé](docs/DEVELOPMENT.md)
- [Standards de code](docs/CODING_STANDARDS.md)
- [Architecture du projet](docs/ARCHITECTURE.md)
- [Système de validation](docs/VALIDATION.md)

---

## 🤔 Questions ?

Si vous avez des questions sur les standards de développement ou le processus de contribution :

1. Consultez d'abord la documentation ([docs/](docs/))
2. Regardez les PRs existantes pour voir des exemples
3. Ouvrez une issue avec le tag `question`

Merci de contribuer à **ebook-translator** ! 🚀
