# CLAUDE.md

Ce fichier fournit des instructions à Claude Code (claude.ai/code) lors du travail avec le code de ce dépôt.

## 📚 Documentation complète

La documentation du projet est organisée en fichiers spécialisés :

### Documentation technique

| Document | Description | Contenu |
|----------|-------------|---------|
| **[docs/SETUP.md](docs/SETUP.md)** | Configuration et installation | Clés API, dépendances, commandes de dev, dépannage |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Architecture technique | Pipeline de traduction, composants clés, flux de données |
| **[docs/LITERARY_ANALYSIS.md](docs/LITERARY_ANALYSIS.md)** | Phase 0 - Analyse littéraire | ContexteTraduction, glossaire, détection chapitres (v0.11.0) |
| **[docs/VALIDATION.md](docs/VALIDATION.md)** | Système de validation | Module validation/, retry progressif, checks structurels |
| **[docs/TEMPLATES.md](docs/TEMPLATES.md)** | Architecture des templates | Templates LLM, bases communes, refactorisation v0.9.0 |
| **[docs/CHANGELOG.md](docs/CHANGELOG.md)** | Historique des versions | Versions 0.2.0 à 0.11.0, changements détaillés |
| **[docs/ROADMAP.md](docs/ROADMAP.md)** | Améliorations futures | Fonctionnalités planifiées (Phase 2 - non implémentées) |

### Documentation pour contributeurs

| Document | Description | Contenu |
|----------|-------------|---------|
| **[CONTRIBUTING.md](CONTRIBUTING.md)** | Guide de contribution principal | Standards de code, workflow Git, processus de développement |
| **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)** | Guide développeur détaillé | Setup environnement, développement incrémental, exemples concrets |
| **[docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md)** | Référence technique des standards | Typage, documentation, tests, architecture, exemples bon/mauvais |

## 📋 Standards de développement

Ce projet suit des **standards de qualité stricts** pour garantir la maintenabilité et la cohérence du code.

### Standards obligatoires

#### 1. Typage strict (OBLIGATOIRE)

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

**Configuration** : Pyright en mode strict (0 errors tolérés)

```bash
# Vérifier les types
poetry run pyright src/
# Doit retourner : "0 errors, 0 warnings"
```

#### 2. Développement incrémental (OBLIGATOIRE)

**Pour toute feature complexe, suivre le processus :**

1. **Décomposer** la feature en sous-tâches testables
2. **Implémenter** une sous-tâche à la fois
3. **Tester** chaque sous-tâche avant d'avancer
4. **Valider** que tout fonctionne ensemble
5. **Commit atomique** pour chaque sous-tâche complétée

**Exemple** : Voir [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#développement-incrémental-en-pratique) pour un exemple détaillé.

#### 3. Documentation (OBLIGATOIRE)

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

    Args:
        original: Textes originaux indexés par numéro de ligne
        translated: Textes traduits indexés par numéro de ligne
        checks: Liste des checks de validation à exécuter

    Returns:
        ValidationResult avec statut et erreurs détectées

    Raises:
        ValueError: Si original et translated ont des clés différentes

    Example:
        >>> result = validate_translation(original, translated, checks)
        >>> assert result.is_valid
    """
    ...
```

#### 4. Tests (OBLIGATOIRE)

- **Tout nouveau code doit avoir des tests unitaires**
- **Coverage minimale de 80%** pour nouveau code
- **Tests doivent passer** avant commit/PR

```bash
# Exécuter les tests
poetry run pytest

# Avec coverage
poetry run pytest --cov=src/ebook_translator
```

### Outils de qualité

Le projet utilise des **outils automatiques** pour garantir la qualité :

- **Pyright** (mode strict) : Type checking
- **Black** : Formatage automatique
- **Isort** : Tri des imports
- **Ruff** : Linting moderne
- **Pre-commit hooks** : Vérifications automatiques avant commit

```bash
# Installation
poetry install --with dev
poetry run pre-commit install

# Vérifications manuelles
poetry run black src/ tests/           # Formatage
poetry run isort src/ tests/           # Imports
poetry run ruff check src/ tests/      # Linting
poetry run pyright src/                # Types

# Tout en une fois
poetry run pre-commit run --all-files
```

### Workflow Git

**Commits conventionnels obligatoires** :

```bash
feat:      # Nouvelle fonctionnalité
fix:       # Correction de bug
refactor:  # Refactoring sans changement de comportement
test:      # Ajout/modification de tests
docs:      # Documentation
chore:     # Maintenance (deps, config, etc.)
```

**Branches** : `feature/<nom>`, `bugfix/<nom>`, `refactor/<nom>`, `docs/<nom>`

### Ressources pour contributeurs

- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Guide complet de contribution
- **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)** - Guide développeur avec exemples
- **[docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md)** - Référence technique détaillée
- **[.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md)** - Template pour PRs

## Vue d'ensemble du projet

Ceci est un outil de traduction d'ebooks qui utilise des API LLM (compatibles OpenAI) pour traduire des fichiers EPUB. L'outil segmente intelligemment le contenu des ebooks, le traduit à l'aide d'appels LLM asynchrones, et reconstruit l'EPUB traduit tout en préservant la structure et les métadonnées.

### Caractéristiques principales

- **Phase 0 - Analyse littéraire** : Extraction automatique du contexte narratif et glossaire pré-rempli (-67% tokens LLM), intégration auto dans Phase 1-2 (v0.12.0)
- **Détection automatique des chapitres** : SequentialChapterDetector via EPUB spine avec contexte narratif
- **Segmentation intelligente** : Découpe le contenu en chunks de 2000 tokens avec chevauchement configurable
- **Traduction parallèle** : Utilise ThreadPoolExecutor pour traductions concurrentes
- **Validation automatique** : Système de validation structurelle avec retry progressif (mode reasoning)
- **Templates refactorisés** : Architecture DRY avec bases communes (-73% duplication)
- **Logging par session** : Organisation claire des logs avec nommage contextuel
- **Rétrocompatibilité** : 0 breaking changes sur 12 versions (0.2.0 → 0.12.0)

## 🚀 Démarrage rapide

### Installation

```bash
# Cloner le dépôt
git clone <repo-url>
cd ebook-translator

# Installer les dépendances
poetry install

# Copier et configurer .env
cp .env.example .env
# Éditer .env et ajouter votre clé API DeepSeek
```

**Configuration minimale** :
```bash
# .env
DEEPSEEK_API_KEY=sk-votre-cle-api-ici
```

Voir [docs/SETUP.md](docs/SETUP.md) pour plus de détails.

### Utilisation

```bash
# Exécuter le traducteur
python -m ebook_translator

# Ou directement
python src/ebook_translator/__main__.py
```

### Tests

```bash
# Exécuter tous les tests
poetry run pytest

# Tests avec couverture
poetry run pytest --cov=src/ebook_translator --cov-report=html

# Vérification des types
poetry run pyright src/ebook_translator
```

## Architecture globale

### Pipeline de traduction

```
EPUB Input
    ↓
[Phase 0: Analyse Littéraire] (optionnelle)
    ├── [SequentialChapterDetector] → Détection chapitres via spine
    ├── [ChapterChunk] → Un chunk par chapitre (8000 tokens)
    ├── [LiteraryAnalysisPhase] → Analyse simplifiée (JSON mode)
    │   ├── render_analyze_simplified() → Template Jinja optimisé
    │   ├── AnalysisValidator.validate() → Validation ContexteTraduction
    │   └── _populate_glossary() → Population automatique
    └── Output: JSON + Glossaire pré-rempli
    ↓
[Phase 1-2: Traduction] (classique)
    ↓
[Segmentator] → Chunks (head/body/tail, 2000 tokens)
    ↓
[ValidationQueue] → [ValidationWorkers (N threads)]
    ↓                       ↓
[LLM Translator] ← [SaveQueue] → [SaveWorker (1 thread)]
    ↓                       ↓
[Parser] → Validated Translations → [Store]
    ↓
[HtmlPage] → Text Replacement
    ↓
EPUB Output
```

**Flux détaillé** :
1. **Chargement EPUB** - Extraction métadonnées et contenu
2. **[Phase 0] Analyse littéraire** (optionnelle) - Extraction contexte + glossaire
3. **Segmentation** - Découpe en chunks avec overlap (défaut: 15%)
4. **[Phase 1] Traduction initiale** - Appels LLM parallèles avec retry automatique
5. **[Phase 2] Raffinage** (optionnel) - Amélioration avec glossaire et contexte
6. **Validation** - Vérification structurelle (lignes, fragments, ponctuation)
7. **Sauvegarde** - Persistance thread-safe via SaveWorker
8. **Reconstruction** - Remplacement texte dans DOM HTML
9. **Génération EPUB** - Création du fichier traduit

Voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) et [docs/LITERARY_ANALYSIS.md](docs/LITERARY_ANALYSIS.md) pour plus de détails.

### Composants clés

**SequentialChapterDetector** ([src/ebook_translator/segmentation/sequential_detector.py](src/ebook_translator/segmentation/sequential_detector.py)) :
- Détection automatique des chapitres via EPUB spine (v0.10.0)
- Parcours séquentiel avec contexte narratif complet
- Méthodes: `get_all_chapters()`, `get_all_chapters_by_spine()`
- Support patterns multiples: "Chapter 1", "Chapitre I", etc.

**LiteraryAnalysisPhase** ([src/ebook_translator/pipeline/phases/literary_analysis.py](src/ebook_translator/pipeline/phases/literary_analysis.py)) :
- Phase 0 optionnelle d'analyse pré-traduction (v0.11.0)
- Extraction contexte narratif + glossaire automatique
- Format simplifié `ContexteTraduction` (-67% tokens LLM)
- Population automatique du glossaire avec `validate_translation()`
- **Intégration automatique** (v0.12.0) : Contexte littéraire passé aux prompts Phase 1-2

**Segmentator** ([src/ebook_translator/segmentation/segmentator.py](src/ebook_translator/segmentation/segmentator.py)) :
- Découpe le contenu en chunks de 2000 tokens (configurable)
- Support overlap_ratio >= 1.0 pour contexte étendu (v0.7.0)
- Système de queue pour gestion multi-chunks

**AsyncLLMTranslator** ([src/ebook_translator/llm/llm.py](src/ebook_translator/llm/llm.py)) :
- Client async OpenAI compatible avec toute API OpenAI
- Retry automatique avec backoff exponentiel (v0.3.0)
- Support mode reasoning (deepseek-reasoner) pour corrections complexes (v0.8.0)
- Support JSON mode pour analyse structurée (v0.10.0)
- Logging contextuel avec création lazy (v0.6.0)

**ValidationWorkerPool** ([src/ebook_translator/validation/](src/ebook_translator/validation/)) :
- Architecture multi-thread : N ValidationWorkers + 1 SaveWorker
- Découplage validation/sauvegarde → +33-50% de throughput
- Retry progressif : tentative 1 (normal) + tentative 2 (reasoning)

**HtmlPage** ([src/ebook_translator/htmlpage/page.py](src/ebook_translator/htmlpage/page.py)) :
- Pattern singleton avec cache pour éviter re-parsing
- Gestion des séparateurs de fragments (`</>`)
- Remplacement texte avec préservation structure DOM

Voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) et [docs/LITERARY_ANALYSIS.md](docs/LITERARY_ANALYSIS.md) pour la liste complète.

## Système de validation

Le système de validation est centré sur le module **validation/** :

### Module `validation/` - Validation structurelle (OBLIGATOIRE)

✅ **Intégré automatiquement** dans le pipeline
- `LineCountCheck` : Vérifie toutes les lignes traduites
- `FragmentCountCheck` : Vérifie le nombre de séparateurs `</>`
- `PunctuationCheck` : Vérifie l'équilibre des paires de guillemets
- `SentenceCheck` : Vérifie le nombre de phrases

**Retry progressif** (v0.8.0) :
- Tentative 1 : Mode normal (`deepseek-chat`)
- Tentative 2 : Mode reasoning (`deepseek-reasoner`)
- **Impact** : +10-20% de taux de succès, -40% de chunks filtrés

**Note** : La validation sémantique (détection de segments non traduits, cohérence terminologique) est actuellement assurée par le glossaire (`src/ebook_translator/glossary.py`) et les transitions entre phases (`src/ebook_translator/transition/`).

Voir [docs/VALIDATION.md](docs/VALIDATION.md) pour plus de détails.

## Architecture des templates LLM

**Catégories** :
- **ANALYZE** (1 template) : Analyse littéraire pré-traduction (Phase 0)
- **TRANSLATE** (4 templates) : Créent nouvelles traductions (Phase 1-2)
- **CORRECT** (3 templates) : Corrigent erreurs structurelles (retry)

**Templates Phase 0** (v0.11.0) :
- `analyze_chapter_simplified.jinja` (80 lignes) : Analyse littéraire format `ContexteTraduction`
- 2 templates de correction: `retry_correct_analysis_invalid_json.jinja`, `retry_correct_analysis_missing_sections.jinja`

**Bases communes** (v0.9.0) :
- `common_translate_rules.jinja` (199 lignes) : Règles partagées TRANSLATE
- `common_correct_rules.jinja` (130 lignes) : Règles partagées CORRECT

**Bénéfices** :
- -73% duplication de code (1260 → 329 lignes partagées)
- -67% tokens LLM Phase 0 (format simplifié)
- 7× plus facile à maintenir (1 fichier au lieu de 7)
- Cohérence 100% garantie

Voir [docs/TEMPLATES.md](docs/TEMPLATES.md) et [docs/LITERARY_ANALYSIS.md](docs/LITERARY_ANALYSIS.md) pour plus de détails.

## Phase 0 : Analyse Littéraire (v0.11.0)

La **Phase 0** est une phase optionnelle d'analyse pré-traduction qui extrait automatiquement :

### 📋 Objectifs

1. **Contexte narratif** : Résumé, tonalité, style, thèmes, références culturelles
2. **Glossaire pré-rempli** : Personnages, lieux, créatures, titres avec propositions de traduction
3. **Pistes de traduction** : Liste concrète d'éléments à préserver/adapter

### 🎯 Avantages

| Aspect | Bénéfice | Impact |
|--------|----------|--------|
| **Cohérence terminologique** | Glossaire pré-rempli dès Phase 1 | -30-50% de conflits |
| **Coût LLM réduit** | Format simplifié `ContexteTraduction` | -67% tokens Phase 0 |
| **Guidance concrète** | Liste structurée de pistes | +15-25% qualité contextuelle |
| **Population automatique** | Intégré dans `LiteraryAnalysisPhase` | Pas de code séparé |

### 📊 Format simplifié (v0.11.0)

**ContexteTraduction** remplace `ChapterAnalysis` (v0.10.0 déprécié) :

```python
class ContexteTraduction(TypedDict):
    chapitre: str
    analyse: AnalyseLitteraire  # 6 champs (résumé, tonalité, style, thèmes, références, pistes)
    glossaire: list[TermeGlossaire]  # 6 champs (terme, type, sexe, description, notes, proposition)
```

**Réduction** :
- -68% lignes de schéma (254 → 80)
- -67% tokens LLM réponse (800-1200 → 300-400)
- -78% sections obligatoires (9 → 2)
- +260% champs utilisés (23% → 83%)

### 🚀 Utilisation

```python
from src.ebook_translator.pipeline.executor import PipelineExecutor
from src.ebook_translator.pipeline.phases.literary_analysis import LiteraryAnalysisPhase
from src.ebook_translator.glossary import Glossary
from pathlib import Path

# 1. Exécuter Phase 0
executor = PipelineExecutor(
    llm=llm,
    html_items=html_items,
    cache_dir=Path("cache"),
    glossary=glossary,  # Sera peuplé automatiquement
    target_language=Language.FRENCH,
    phases=[LiteraryAnalysisPhase],  # Phase 0 uniquement
)
executor.run()

# 2. Glossaire déjà peuplé !
glossary.save()
print(f"Termes extraits: {len(glossary.glossary)}")

# 3. Analyses sauvées dans cache/literary_analysis/Chapter_X.json
```

Voir [example_phase0_analysis.py](example_phase0_analysis.py) pour un exemple complet.

### 📁 Fichiers générés

```
cache/
├── literary_analysis/          # Store Phase 0
│   ├── Chapter_1.json         # {"0": "...ContexteTraduction JSON..."}
│   ├── Chapter_2.json
│   └── ...
└── glossary.json              # Glossaire peuplé automatiquement
```

### 🔗 Documentation complète

Voir [docs/LITERARY_ANALYSIS.md](docs/LITERARY_ANALYSIS.md) pour :
- Architecture détaillée
- Schéma `ContexteTraduction`
- Guide de migration depuis v0.10.0
- Limitations et améliorations futures

## Configuration

### Variables d'environnement

| Variable | Obligatoire | Défaut | Description |
|----------|-------------|--------|-------------|
| `DEEPSEEK_API_KEY` | ✅ Oui | - | Clé API DeepSeek |
| `DEEPSEEK_URL` | ❌ Non | `https://api.deepseek.com` | URL de base API |
| `OPENAI_API_KEY` | ❌ Non | - | Clé API OpenAI (alternative) |

### Paramètres recommandés

```python
from ebook_translator import EpubTranslator, Language
from ebook_translator.llm import LLM

# Configuration LLM
llm = LLM(
    model_name="deepseek-chat",
    url="https://api.deepseek.com",
    max_retries=3,        # Retry automatique (défaut)
    retry_delay=1.0,      # Délai initial en secondes
    temperature=0.5,      # Cohérence optimale (défaut depuis v0.4.0)
)

# Configuration traduction
translator = EpubTranslator(llm, epub_path="book.epub")
translator.translate(
    target_language=Language.FRENCH,
    output_epub="book_fr.epub",
    max_concurrent=2,     # Nombre de traductions parallèles
    overlap_ratio=0.15,   # Chevauchement de contexte (15%)
)
```

**Notes** :
- `overlap_ratio < 1.0` : Pourcentage de max_tokens (ex: 0.15 = 15%)
- `overlap_ratio >= 1.0` : Multiple de max_tokens (ex: 2.0 = 200%, contexte étendu)
- `max_concurrent` : Réduire à 1-2 si rate limit fréquent

Voir [docs/SETUP.md](docs/SETUP.md) pour la configuration complète.

## Format des traductions

### Balises obligatoires

**Numérotation `<N/>`** :
- Chaque ligne commence par `<0/>`, `<1/>`, etc.
- OBLIGATOIRE : Reproduire EXACTEMENT dans la traduction
- INTERDICTION : Modifier, supprimer, ajouter des numéros

**Séparateurs `</>`** :
- Marquent les fragments multiples dans une même balise HTML
- OBLIGATOIRE : Préserver EXACTEMENT le même nombre
- Exemple : `<0/>Hello</>world` → `<0/>Bonjour</>monde`

**Marqueur de fin `[=[END]=]`** :
- Toutes les traductions se terminent par ce marqueur
- Utilisé pour validation de complétude

### Exemple complet

```
Source:
<0/>The cat is sleeping.
<1/>It</>dreams of mice.
[=[END]=]

Traduction:
<0/>Le chat dort.
<1/>Il</>rêve de souris.
[=[END]=]
```

## Structure du projet

```
ebook-translator/
├── src/ebook_translator/     # Code source principal
│   ├── analysis/            # Phase 0 - Analyse littéraire (v0.10.0+)
│   │   ├── translation_context.py  # Schéma ContexteTraduction (v0.11.0)
│   │   ├── validator.py            # Validation JSON structure
│   │   └── analysis_exporter.py    # Export Markdown (WIP)
│   ├── checks/              # Validation structurelle
│   │   ├── check_tests/    # 5 checks: LineCount, FragmentCount, Punctuation, Sentence, ValidateAnalysis
│   │   ├── pipeline.py     # ValidationPipeline orchestrateur
│   │   └── retry_helper.py # Retry progressif avec mode reasoning
│   ├── glossary.py          # Glossaire pour cohérence terminologique
│   ├── htmlpage/            # Manipulation HTML/DOM (HtmlPage, TagKey)
│   ├── llm/                 # Client LLM et template renderers
│   │   ├── llm.py          # Support JSON mode (v0.10.0)
│   │   ├── template_renderers.py  # render_analyze_simplified() (v0.11.0)
│   │   └── llm_config.py   # Configuration LLM
│   ├── pipeline/            # Pipeline multi-phases (v0.9.0+)
│   │   ├── phases/         # Phases individuelles
│   │   │   ├── literary_analysis.py  # Phase 0 (v0.11.0)
│   │   │   ├── initial_translation.py  # Phase 1
│   │   │   └── refinement.py  # Phase 2
│   │   ├── executor.py     # Exécuteur de pipeline
│   │   └── store_manager.py  # Gestion des stores par phase
│   ├── segmentation/        # Segmentation du contenu
│   │   ├── sequential_detector.py  # Détection chapitres (v0.10.0)
│   │   ├── chapter_chunk.py        # ChapterChunk (Phase 0)
│   │   ├── segmentator.py          # Segmentation classique
│   │   └── chunk.py                # Chunk de traduction
│   ├── transition/          # Gestion des transitions entre phases
│   └── validation/          # Architecture multi-thread (ValidationWorkerPool, SaveWorker)
├── template/                # Templates Jinja2 pour prompts LLM
│   ├── analyze_chapter_simplified.jinja  # Phase 0 analyse (v0.11.0)
│   ├── retry_correct_analysis_*.jinja    # Correction analyses Phase 0
│   ├── common_translate_rules.jinja      # Règles communes TRANSLATE
│   ├── common_correct_rules.jinja        # Règles communes CORRECT
│   └── [10+ templates spécifiques]
├── tests/                   # Tests unitaires (140+ tests, organisation modulaire)
│   ├── analysis/           # Tests Phase 0
│   ├── checks/             # Tests validation
│   ├── glossary/           # Tests glossaire
│   ├── htmlpage/           # Tests manipulation HTML
│   ├── llm/                # Tests LLM
│   ├── logger/             # Tests logging
│   ├── pipeline/           # Tests pipeline
│   ├── segmentation/       # Tests segmentation
│   ├── stores/             # Tests persistence
│   ├── translation/        # Tests traduction
│   ├── transition/         # Tests transitions
│   └── validation/         # Tests ValidationWorkerPool
├── docs/                    # Documentation spécialisée
│   ├── SETUP.md            # Configuration et installation
│   ├── ARCHITECTURE.md     # Architecture technique
│   ├── LITERARY_ANALYSIS.md  # Phase 0 - Analyse littéraire (v0.11.0)
│   ├── VALIDATION.md       # Système de validation
│   ├── TEMPLATES.md        # Architecture des templates
│   ├── CHANGELOG.md        # Historique des versions
│   ├── ROADMAP.md          # Améliorations futures
│   ├── DEVELOPMENT.md      # Guide développeur détaillé
│   └── CODING_STANDARDS.md # Référence technique des standards
├── .github/                 # Configuration GitHub
│   └── PULL_REQUEST_TEMPLATE.md  # Template pour PRs
├── logs/                    # Logs de traduction (par session)
│   └── run_YYYYMMDD_HHMMSS/ # Session unique
├── cache/                   # Cache et glossaires
│   ├── literary_analysis/  # Store Phase 0 (JSON)
│   └── glossary.json       # Glossaire pré-rempli
├── example_phase0_analysis.py  # Exemple Phase 0 (v0.11.0)
├── CONTRIBUTING.md          # Guide de contribution
├── .pre-commit-config.yaml  # Configuration pre-commit hooks
└── pyproject.toml           # Configuration Python (Poetry, Pyright strict, Black, Ruff, etc.)
```

## Historique des versions

Versions principales (0.2.0 → 0.11.0) :

| Version | Date | Fonctionnalité | Impact |
|---------|------|----------------|--------|
| 0.2.0 | 2025-10-19 | Stabilisation (4 bugs critiques) | Bugs corrigés |
| 0.3.0 | 2025-10-20 | Gestion d'erreurs robuste | Retry avec backoff |
| 0.3.1 | 2025-10-21 | Validation stricte des lignes | Lignes manquantes détectées |
| 0.4.0 | 2025-10-21 | Qualité traductions (few-shot) | +20-30% qualité |
| 0.5.0 | 2025-10-21 | Validation post-traduction | Cohérence terminologique |
| 0.6.0 | 2025-10-23 | Logging par session | Logs organisés |
| 0.7.0 | 2025-10-23 | Support overlap_ratio > 1.0 | Contexte étendu |
| 0.8.0 | 2025-10-28 | Retry progressif + reasoning | +10-20% succès retry |
| 0.9.0 | 2025-10-29 | Refactorisation templates (DRY) | -388 lignes, +73% lisibilité |
| **0.10.x** | **2025-11-xx** | **Phase 0 - Analyse littéraire complète** | **Détection chapitres + analyse** |
| **0.11.0** | **2025-11-15** | **Phase 0 - Format simplifié** | **-67% tokens LLM Phase 0** |

**Statistiques cumulées** :
- 140+ tests unitaires (organisation modulaire)
- 0 breaking changes (rétrocompatibilité totale)
- +35-45% de qualité globale
- -25% de duplication de code
- Architecture pipeline multi-phases complète

Voir [docs/CHANGELOG.md](docs/CHANGELOG.md) pour l'historique complet.

## Roadmap (Phase 2 - non implémentée)

Améliorations futures planifiées :

### Haute priorité
- Contexte avancé (métadonnées, cache sémantique)
- Amélioration du glossaire (détection conflits, filtrage intelligent, export/import)
- Optimisation overlap (adaptatif, compression, cache)
- Tests complets (chunk_queue, régression, performance)

### Moyenne priorité
- Stratégies de fallback (mode reprise, rapports HTML)
- Gestion avancée des logs (rotation, compression, dashboard)
- Métriques et monitoring (statistiques, graphes, export)
- Tooling templates (migration, linter, générateur)

**Impact global attendu** : +35-45% de qualité, -25-35% de coût

Voir [docs/ROADMAP.md](docs/ROADMAP.md) pour la roadmap complète.

## Commandes utiles

### Développement

```bash
# Installer dépendances (production)
poetry install

# Installer dépendances de dev (qualité de code)
poetry install --with dev

# Installer pre-commit hooks (automatisation)
poetry run pre-commit install

# Exécuter le traducteur
python -m ebook_translator
```

### Tests et validation

```bash
# Tests
poetry run pytest                                          # Tous les tests
poetry run pytest tests/test_segment.py -v                # Test spécifique
poetry run pytest --cov=src/ebook_translator              # Avec couverture (≥80% requis)

# Vérification des types (mode strict)
poetry run pyright src/ebook_translator                   # 0 errors requis
```

### Qualité de code

```bash
# Formatage automatique
poetry run black src/ tests/                              # Formatage du code
poetry run isort src/ tests/                              # Tri des imports

# Linting
poetry run ruff check src/ tests/                         # Analyse statique
poetry run ruff check --fix src/ tests/                   # Auto-correction

# Vérification complète (recommandé avant commit)
poetry run pre-commit run --all-files                     # Tous les hooks

# Vérifications individuelles
poetry run black --check src/ tests/                      # Check formatage
poetry run isort --check-only src/ tests/                 # Check imports
poetry run ruff check src/ tests/                         # Check linting
poetry run pyright src/                                   # Check types
```

### Tests des templates

```bash
# Lister tous les templates
poetry run python test_template_manual.py list

# Tester un template spécifique
poetry run python test_template_manual.py translate_base

# Tester tous les templates
poetry run python test_all_templates.py
```

### Dépannage

**Erreur "API key not found"** :
```bash
# Vérifier .env
cat .env

# Vérifier chargement
python -c "from dotenv import load_dotenv; load_dotenv(); import os; print(os.getenv('DEEPSEEK_API_KEY'))"
```

**Rate limit exceeded** :
- Réduire `max_concurrent` à 1-2
- Augmenter `retry_delay`

Voir [docs/SETUP.md](docs/SETUP.md) pour plus de dépannage.

## ✅ Checklist qualité avant commit/PR

Avant chaque commit ou Pull Request, vérifier que :

### Code

- [ ] Tous les paramètres de fonction sont typés
- [ ] Tous les retours de fonction sont typés (même `-> None`)
- [ ] Variables complexes explicitement typées
- [ ] Pyright strict sans erreurs : `poetry run pyright src/`
- [ ] Code formaté : `poetry run black src/ tests/`
- [ ] Imports triés : `poetry run isort src/ tests/`
- [ ] Ruff linting OK : `poetry run ruff check src/ tests/`

### Documentation

- [ ] Docstrings ajoutées pour nouvelles fonctions/classes publiques
- [ ] Format Google UNIQUEMENT (Args, Returns, Raises, Example) - aucun autre format accepté
- [ ] Commentaires inline pour code complexe
- [ ] CHANGELOG.md mis à jour (si version bump)

### Tests

- [ ] Tests unitaires pour tout nouveau code
- [ ] Tests d'intégration pour features multi-composants
- [ ] Tous les tests passent : `poetry run pytest`
- [ ] Coverage ≥ 80% : `poetry run pytest --cov=src/ebook_translator`

### Git

- [ ] Commits conventionnels (feat:, fix:, refactor:, test:, docs:, chore:)
- [ ] Messages de commit descriptifs
- [ ] Branche nommée correctement (feature/, bugfix/, refactor/, docs/)
- [ ] Pas de conflits avec master
- [ ] Pre-commit hooks OK : `poetry run pre-commit run --all-files`

### Vérification rapide

```bash
# Commande unique pour vérifier tous les critères
poetry run pytest && \
poetry run pyright src/ && \
poetry run pre-commit run --all-files

# Si tout est vert (✅), vous êtes prêt à commit/PR !
```

## Ressources

### Documentation technique

- **[docs/SETUP.md](docs/SETUP.md)** - Configuration et installation
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** - Architecture technique
- **[docs/LITERARY_ANALYSIS.md](docs/LITERARY_ANALYSIS.md)** - Phase 0 - Analyse littéraire (v0.11.0)
- **[docs/VALIDATION.md](docs/VALIDATION.md)** - Système de validation
- **[docs/TEMPLATES.md](docs/TEMPLATES.md)** - Architecture des templates
- **[docs/CHANGELOG.md](docs/CHANGELOG.md)** - Historique des versions
- **[docs/ROADMAP.md](docs/ROADMAP.md)** - Roadmap

### Documentation pour contributeurs

- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Guide de contribution complet
- **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)** - Guide développeur avec exemples concrets
- **[docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md)** - Référence technique des standards
- **[.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md)** - Template pour PRs

### Exemples d'utilisation

- **[example_phase0_analysis.py](example_phase0_analysis.py)** - Exemple Phase 0 (Analyse littéraire)
- **[example_pipeline.py](example_pipeline.py)** - Exemple pipeline complet Phase 1-2

### Liens externes

- **GitHub** : [Repository URL]
- **Issues** : Rapporter les bugs sur GitHub Issues
- **API DeepSeek** : https://platform.deepseek.com

## Licence

[À compléter]
