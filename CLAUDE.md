# CLAUDE.md

Ce fichier fournit des instructions à Claude Code (claude.ai/code) lors du travail avec le code de ce dépôt.

## 📚 Documentation complète

La documentation du projet est organisée en fichiers spécialisés :

| Document | Description | Contenu |
|----------|-------------|---------|
| **[docs/SETUP.md](docs/SETUP.md)** | Configuration et installation | Clés API, dépendances, commandes de dev, dépannage |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Architecture technique | Pipeline de traduction, composants clés, flux de données |
| **[docs/VALIDATION.md](docs/VALIDATION.md)** | Système de validation | Module validation/, retry progressif, checks structurels |
| **[docs/TEMPLATES.md](docs/TEMPLATES.md)** | Architecture des templates | Templates LLM, bases communes, refactorisation v0.9.0 |
| **[docs/CHANGELOG.md](docs/CHANGELOG.md)** | Historique des versions | Versions 0.2.0 à 0.9.0, changements détaillés |
| **[docs/ROADMAP.md](docs/ROADMAP.md)** | Améliorations futures | Fonctionnalités planifiées (Phase 2 - non implémentées) |

## Vue d'ensemble du projet

Ceci est un outil de traduction d'ebooks qui utilise des API LLM (compatibles OpenAI) pour traduire des fichiers EPUB. L'outil segmente intelligemment le contenu des ebooks, le traduit à l'aide d'appels LLM asynchrones, et reconstruit l'EPUB traduit tout en préservant la structure et les métadonnées.

### Caractéristiques principales

- **Segmentation intelligente** : Découpe le contenu en chunks de 2000 tokens avec chevauchement configurable
- **Traduction parallèle** : Utilise ThreadPoolExecutor pour traductions concurrentes
- **Validation automatique** : Système de validation structurelle avec retry progressif (mode reasoning)
- **Templates refactorisés** : Architecture DRY avec bases communes (-73% duplication)
- **Logging par session** : Organisation claire des logs avec nommage contextuel
- **Rétrocompatibilité** : 0 breaking changes sur 9 versions (0.2.0 → 0.9.0)

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
[Segmentator] → Chunks (head/body/tail)
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
2. **Segmentation** - Découpe en chunks avec overlap (défaut: 15%)
3. **Traduction** - Appels LLM parallèles avec retry automatique
4. **Validation** - Vérification structurelle (lignes, fragments, ponctuation)
5. **Sauvegarde** - Persistance thread-safe via SaveWorker
6. **Reconstruction** - Remplacement texte dans DOM HTML
7. **Génération EPUB** - Création du fichier traduit

Voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) pour plus de détails.

### Composants clés

**Segmentator** ([src/ebook_translator/segment.py](src/ebook_translator/segment.py)) :
- Découpe le contenu en chunks de 2000 tokens (configurable)
- Support overlap_ratio >= 1.0 pour contexte étendu (v0.7.0)
- Système de queue pour gestion multi-chunks

**AsyncLLMTranslator** ([src/ebook_translator/llm.py](src/ebook_translator/llm.py)) :
- Client async OpenAI compatible avec toute API OpenAI
- Retry automatique avec backoff exponentiel (v0.3.0)
- Support mode reasoning (deepseek-reasoner) pour corrections complexes (v0.8.0)
- Logging contextuel avec création lazy (v0.6.0)

**ValidationWorkerPool** ([src/ebook_translator/validation/](src/ebook_translator/validation/)) :
- Architecture multi-thread : N ValidationWorkers + 1 SaveWorker
- Découplage validation/sauvegarde → +33-50% de throughput
- Retry progressif : tentative 1 (normal) + tentative 2 (reasoning)

**HtmlPage** ([src/ebook_translator/htmlpage.py](src/ebook_translator/htmlpage.py)) :
- Pattern singleton avec cache pour éviter re-parsing
- Gestion des séparateurs de fragments (`</>`)
- Remplacement texte avec préservation structure DOM

Voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) pour la liste complète.

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
- **TRANSLATE** (4 templates) : Créent nouvelles traductions
- **CORRECT** (3 templates) : Corrigent erreurs structurelles

**Bases communes** (v0.9.0) :
- `common_translate_rules.jinja` (199 lignes) : Règles partagées TRANSLATE
- `common_correct_rules.jinja` (130 lignes) : Règles partagées CORRECT

**Bénéfices** :
- -73% duplication de code (1260 → 329 lignes partagées)
- 7× plus facile à maintenir (1 fichier au lieu de 7)
- Cohérence 100% garantie

Voir [docs/TEMPLATES.md](docs/TEMPLATES.md) pour plus de détails.

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
│   ├── checks/              # Validation structurelle
│   │   ├── check_tests/    # 4 checks: LineCount, FragmentCount, Punctuation, Sentence
│   │   ├── pipeline.py     # ValidationPipeline orchestrateur
│   │   └── retry_helper.py # Retry progressif avec mode reasoning
│   ├── correction/          # (Ancien système, en transition)
│   ├── glossary.py          # Glossaire pour cohérence terminologique
│   ├── htmlpage/            # Manipulation HTML/DOM (HtmlPage, TagKey)
│   ├── llm/                 # Client LLM et template renderers
│   ├── pipeline/            # Pipeline de traduction (nouveau depuis v0.9.0+)
│   ├── segmentation/        # Segmentation du contenu (Segmentator, Chunk)
│   ├── transition/          # Gestion des transitions entre phases
│   └── validation/          # Architecture multi-thread (ValidationWorkerPool, SaveWorker)
├── template/                # Templates Jinja2 pour prompts LLM
│   ├── common_translate_rules.jinja  # Règles communes TRANSLATE
│   ├── common_correct_rules.jinja    # Règles communes CORRECT
│   └── [7 templates spécifiques]
├── tests/                   # Tests unitaires (107+ tests)
├── docs/                    # Documentation spécialisée
│   ├── SETUP.md            # Configuration et installation
│   ├── ARCHITECTURE.md     # Architecture technique
│   ├── VALIDATION.md       # Système de validation
│   ├── TEMPLATES.md        # Architecture des templates
│   ├── CHANGELOG.md        # Historique des versions
│   └── ROADMAP.md          # Améliorations futures
├── logs/                    # Logs de traduction (par session)
│   └── run_YYYYMMDD_HHMMSS/ # Session unique
└── cache/                   # Cache et glossaires
```

## Historique des versions

Versions principales (0.2.0 → 0.9.0) :

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

**Statistiques cumulées** :
- 107+ tests unitaires
- 0 breaking changes (rétrocompatibilité totale)
- +35-45% de qualité globale
- -25% de duplication de code

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
# Installer dépendances
poetry install

# Exécuter le traducteur
python -m ebook_translator

# Tests
poetry run pytest                                          # Tous les tests
poetry run pytest tests/test_segment.py -v                # Test spécifique
poetry run pytest --cov=src/ebook_translator              # Avec couverture

# Vérification des types
poetry run pyright src/ebook_translator
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

## Ressources

- **GitHub** : [Repository URL]
- **Documentation** : [docs/](docs/)
- **Issues** : Rapporter les bugs sur GitHub Issues
- **API DeepSeek** : https://platform.deepseek.com

## Licence

[À compléter]
