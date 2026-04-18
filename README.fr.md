# Traducteur d'Ebooks

> Traduisez des fichiers EPUB en utilisant des Large Language Models (DeepSeek, OpenAI et autres APIs compatibles OpenAI)

[🇬🇧 English version](README.md)

## Vue d'ensemble

**Ebook Translator** est un outil Python qui traduit des fichiers EPUB en utilisant des Large Language Models (LLM) tels que DeepSeek, OpenAI et d'autres APIs compatibles OpenAI. L'outil segmente intelligemment le contenu des ebooks, le traduit à l'aide d'appels LLM asynchrones, et reconstruit l'EPUB traduit tout en préservant la structure et les métadonnées.

## Fonctionnalités

- **Traduction EPUB**: Traduit des fichiers EPUB entiers en maintenant la structure
- **Propulsé par LLM**: Utilise des modèles de langage avancés (DeepSeek, OpenAI, etc.)
- **Segmentation intelligente**: Découpe intelligemment le contenu avec limites de tokens et chevauchement
- **Traitement asynchrone**: Parallélise les appels de traduction pour de meilleures performances
- **Préservation des métadonnées**: Conserve le titre, les auteurs et la structure d'origine
- **Structure HTML**: Préserve le formatage, les images, le CSS et la mise en page
- **Validation automatique**: Validation structurelle avec retry progressif (mode reasoning)
- **Logging intelligent**: Logs par session avec nommage contextuel
- **Contrôle qualité**: 4 vérifications structurelles (lignes, fragments, ponctuation, phrases)
- **Architecture de templates**: Templates DRY avec règles partagées (-73% duplication)

## Prérequis

- Python 3.12 ou supérieur
- Poetry (pour la gestion des dépendances)
- Clé API pour DeepSeek ou OpenAI

## Installation

1. **Cloner le dépôt**:
   ```bash
   git clone https://github.com/NeOzay/ebook-translator.git
   cd ebook-translator
   ```

2. **Installer les dépendances**:
   ```bash
   uv sync
   ```

3. **Configurer les clés API**:
   ```bash
   cp .env.example .env
   ```

   Éditez `.env` et ajoutez votre clé API:
   ```bash
   API_KEY=sk-votre-cle-api-ici
   ```

### Obtenir des clés API

**DeepSeek** (Recommandé):
- Créez un compte sur [DeepSeek Platform](https://platform.deepseek.com)
- Accédez à [API Keys](https://platform.deepseek.com/api_keys)
- Générez une nouvelle clé API

**OpenAI** (Alternative):
- Créez un compte sur [OpenAI Platform](https://platform.openai.com)
- Accédez à [API Keys](https://platform.openai.com/api-keys)
- Générez une nouvelle clé API

## Utilisation

### Utilisation de base

Créez un fichier Python (par exemple `translate.py`) :

```python
from ebook_translator import Language, LLM, EpubTranslator

# Configuration du LLM
llm = LLM(
    model_name="deepseek-chat",
    url="https://api.deepseek.com",
    max_retries=3,        # Retry automatique (défaut)
    retry_delay=1.0,      # Délai initial en secondes
    temperature=0.5,      # Cohérence optimale (défaut depuis v0.4.0)
)

# Traduction de l'EPUB
translator = EpubTranslator(llm, epub_path="mon_livre.epub")
translator.translate(
    target_language=Language.FRENCH,
    output_epub="mon_livre_traduit.epub",
    max_concurrent=2,     # Nombre de traductions parallèles
    overlap_ratio=0.15,   # Chevauchement de contexte (15%)
)
```

Puis exécutez :
```bash
python translate.py
```

### Exemple complet

Voir [start.py](start.py) pour un exemple de configuration complète avec tous les paramètres disponibles.

## Configuration

### Variables d'environnement

| Variable | Obligatoire | Défaut | Description |
|----------|-------------|--------|-------------|
| `DEEPSEEK_API_KEY` | ✅ Oui | - | Clé API DeepSeek pour l'authentification |
| `DEEPSEEK_URL` | ❌ Non | `https://api.deepseek.com` | URL de base de l'API |
| `OPENAI_API_KEY` | ❌ Non | - | Clé API OpenAI (alternative à DeepSeek) |

## Développement

**Vérification des types**:
```bash
basedpyright src/ebook_translator
```

**Exécuter les tests**:
```bash
pytest tests/
```

## Architecture

Le pipeline de traduction suit ce flux:

1. **Chargement EPUB** - Extraction des métadonnées et du contenu
2. **Segmentation** - Découpe du contenu avec chevauchement (défaut: 15%)
3. **Traduction** - Appels LLM parallèles avec retry automatique
4. **Validation** - Vérification structurelle (lignes, fragments, ponctuation)
5. **Sauvegarde** - Persistance thread-safe via SaveWorker
6. **Reconstruction** - Remplacement du texte dans le DOM HTML
7. **Génération EPUB** - Création du fichier traduit

### Composants clés

**Segmentator** ([segmentation/segmentator.py](src/ebook_translator/segmentation/segmentator.py)):
- Découpe le contenu en segments de 2000 tokens (configurable)
- Support overlap_ratio >= 1.0 pour contexte étendu (v0.7.0)
- Système de queue multi-chunks

**ValidationWorkerPool** ([validation/](src/ebook_translator/validation/)):
- Architecture multi-thread : N ValidationWorkers + 1 SaveWorker
- Découplage validation/sauvegarde → +33-50% de throughput
- Retry progressif : tentative 1 (normal) + tentative 2 (reasoning)

**Client LLM** ([llm/llm.py](src/ebook_translator/llm/llm.py)):
- Client async OpenAI compatible avec toute API OpenAI
- Retry automatique avec backoff exponentiel (v0.3.0)
- Support mode reasoning (deepseek-reasoner) pour corrections complexes (v0.8.0)
- Logging contextuel avec création lazy (v0.6.0)

**Vérifications de validation** ([checks/](src/ebook_translator/checks/)):
- `LineCountCheck` : Vérifie que toutes les lignes sont traduites
- `FragmentCountCheck` : Vérifie le nombre de séparateurs `</>`
- `PunctuationCheck` : Vérifie l'équilibre des paires de guillemets
- `SentenceCheck` : Vérifie le nombre de phrases

### Architecture des templates

**Catégories** :
- **TRANSLATE** (4 templates) : Créent de nouvelles traductions
- **CORRECT** (3 templates) : Corrigent les erreurs structurelles

**Bases communes** (v0.9.0) :
- `common_translate_rules.jinja` (199 lignes) : Règles partagées TRANSLATE
- `common_correct_rules.jinja` (130 lignes) : Règles partagées CORRECT

**Bénéfices** :
- -73% de duplication de code (1260 → 329 lignes partagées)
- 7× plus facile à maintenir (1 fichier au lieu de 7)
- Cohérence 100% garantie

### Structure du projet

```
ebook-translator/
├── src/ebook_translator/
│   ├── checks/              # Validation structurelle
│   │   ├── check_tests/    # 4 checks: LineCount, FragmentCount, Punctuation, Sentence
│   │   ├── pipeline.py     # ValidationPipeline orchestrateur
│   │   └── retry_helper.py # Retry progressif avec mode reasoning
│   ├── glossary.py          # Glossaire pour cohérence terminologique
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
└── logs/                    # Logs de traduction (par session)
    └── run_YYYYMMDD_HHMMSS/ # Session unique
```

Pour plus de détails, consultez la documentation complète dans [docs/](docs/) ou [CLAUDE.md](CLAUDE.md).

## Documentation

Le projet inclut une documentation complète :

| Document | Description |
|----------|-------------|
| **[CLAUDE.md](CLAUDE.md)** | Vue d'ensemble complète et démarrage rapide |
| **[docs/SETUP.md](docs/SETUP.md)** | Configuration, installation, dépannage |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Architecture technique, composants |
| **[docs/VALIDATION.md](docs/VALIDATION.md)** | Système de validation, retry progressif |
| **[docs/TEMPLATES.md](docs/TEMPLATES.md)** | Architecture des templates LLM |
| **[docs/CHANGELOG.md](docs/CHANGELOG.md)** | Historique des versions (v0.2.0 → v0.9.0) |
| **[docs/ROADMAP.md](docs/ROADMAP.md)** | Améliorations futures (Phase 2) |

## Sécurité

**IMPORTANT**:
- ⚠️ Ne commitez **JAMAIS** le fichier `.env` dans git (déjà dans `.gitignore`)
- ⚠️ Ne partagez **JAMAIS** vos clés API publiquement
- ⚠️ Si une clé est compromise, **révoquez-la immédiatement** sur la plateforme

## Licence

Ce projet est sous licence MIT.

## Auteur

**NeOzay** - [neozay.ozay@gmail.com](mailto:neozay.ozay@gmail.com)

## Liens

- [Page d'accueil](https://github.com/NeOzay/ebook-translator)
- [Issues](https://github.com/NeOzay/ebook-translator/issues)

## Contribution

Les contributions sont les bienvenues ! N'hésitez pas à soumettre une Pull Request.
