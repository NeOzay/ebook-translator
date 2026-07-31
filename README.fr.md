# Traducteur d'Ebooks

> Traduisez des fichiers EPUB en utilisant des Large Language Models (DeepSeek, OpenAI et autres APIs compatibles OpenAI)

[🇬🇧 English version](README.md)

## Vue d'ensemble

**Ebook Translator** est un outil Python qui traduit des fichiers EPUB en utilisant des Large Language Models (LLM) tels que DeepSeek, OpenAI et d'autres APIs compatibles OpenAI. L'outil segmente le contenu des ebooks, le traduit via un pipeline multi-phases, et reconstruit l'EPUB traduit en préservant la structure et les métadonnées.

## Fonctionnalités

- **Traduction EPUB** : traduit des fichiers EPUB entiers en maintenant la structure
- **Pipeline multi-phases** : analyse littéraire et extraction de glossaire optionnelles, puis traduction et raffinage
- **Propulsé par LLM** : utilise des modèles de langage avancés (DeepSeek, OpenAI, etc.)
- **Segmentation intelligente** : découpe le contenu avec limites de tokens et chevauchement configurable
- **Traitement parallèle** : parallélise les appels de traduction pour de meilleures performances
- **Préservation des métadonnées** : conserve le titre, les auteurs et la structure d'origine
- **Structure HTML** : préserve le formatage, les images, le CSS et la mise en page
- **Validation en deux temps** : schéma Pydantic d'abord, puis checks de contenu avec corrections LLM ciblées
- **Apprentissage du glossaire** : cohérence terminologique avec propositions pondérées et détection de conflits
- **Logging intelligent** : logs par session avec nommage contextuel

## Prérequis

- Python 3.14 ou supérieur
- [uv](https://docs.astral.sh/uv/) pour la gestion des dépendances
- Clé API pour DeepSeek ou OpenAI

## Installation

1. **Cloner le dépôt** :
   ```bash
   git clone https://github.com/NeOzay/ebook-translator.git
   cd ebook-translator
   ```

2. **Installer les dépendances** :
   ```bash
   uv sync --group dev
   ```

3. **Configurer les clés API** :
   ```bash
   cp .env.example .env
   ```

   Éditez `.env` et ajoutez votre clé API :
   ```bash
   API_KEY=sk-votre-cle-api-ici
   ```

### Obtenir des clés API

**DeepSeek** (recommandé) :
- Créez un compte sur [DeepSeek Platform](https://platform.deepseek.com)
- Accédez à [API Keys](https://platform.deepseek.com/api_keys)
- Générez une nouvelle clé API

**OpenAI** (alternative) :
- Créez un compte sur [OpenAI Platform](https://platform.openai.com)
- Accédez à [API Keys](https://platform.openai.com/api-keys)
- Générez une nouvelle clé API

## Utilisation

Le pipeline se configure via des builders chaînables :

```python
from pathlib import Path

from ebook_translator import Language, LLMBuilder, PhasesBuilder, PipelineBuilder
from ebook_translator.llm.clients.deepseek import Deepseek, DeepseekModels

stats = (
    PipelineBuilder()
    .epub(Path("mon_livre.epub"))
    .output(Path("mon_livre_traduit.epub"))
    .language(Language.FRENCH)
    .llm(
        LLMBuilder().default_client(
            Deepseek(
                DeepseekModels.FLASH,
                thinking=False,
                config={"temperature": 0.5},
            )
        )
    )
    .phases(
        PhasesBuilder()
        .add_literary_analysis()
        .add_initial_translation()
        .add_refinement()
    )
    .workers(2)
    .run()
)

for phase_name, phase_stats in stats.items():
    print(f"{phase_name} : {phase_stats.chunks_validated} chunks validés")
```

Le modèle, le mode thinking et les paramètres d'échantillonnage appartiennent au **client** : chaque provider a sa propre URL de base et sa propre enum de modèles. `LLMBuilder` ne porte que les options de `LLM` (`prompt_dir`, `max_retries`, `retry_delay`, `glossary_max_terms`).

### Autres exemples

Voir [examples/](examples/) — en particulier [example_pipeline.py](examples/example_pipeline.py) pour une configuration complète et [example_phase0_analysis.py](examples/example_phase0_analysis.py) pour une exécution limitée à l'analyse littéraire.

## Configuration

### Variables d'environnement

| Variable | Obligatoire | Description |
|----------|-------------|-------------|
| `API_KEY` | ✅ Oui | Clé API utilisée par le client, chargée depuis `.env` |

`API_KEY` est la seule variable lue par le code ([llm/clients/client.py](src/ebook_translator/llm/clients/client.py)). Une clé passée explicitement au client (`Deepseek(..., api_key=...)`) est prioritaire. L'URL de base n'est pas configurable par l'environnement : c'est un attribut de classe du client (`Deepseek.base_url`).

## Développement

**Vérification des types** (doit retourner 0 erreur) :
```bash
uv run basedpyright src/
```

**Exécuter les tests** :
```bash
uv run pytest --no-cov
```

`uv run pytest` seul conserve le seuil `--cov-fail-under=80` de `pyproject.toml`.
La couverture est aujourd'hui à ~72 %, la commande sort donc en 1 même quand tous
les tests passent.

**Tous les contrôles qualité** :
```bash
uv run pre-commit run --all-files
```

## Architecture

Le pipeline exécute une liste de phases configurable, dans l'ordre :

```
EPUB → [Phase 0 : analyse littéraire]   (optionnelle, séquentielle)
     → [Phase glossaire]                 (optionnelle, séquentielle)
     → [Phase 1 : traduction initiale]   (parallèle)
     → [Phase 2 : raffinage]             (séquentielle)
     → EPUB de sortie
```

Dans chaque phase, `PhaseExecutor` segmente le contenu, appelle le LLM, valide la sortie contre un schéma Pydantic, puis confie le résultat au pool de validation. Les chunks validés sont écrits en cache par un thread dédié, et l'EPUB final est reconstruit depuis le DOM HTML.

### Composants clés

**Builders** ([pipeline/builder.py](src/ebook_translator/pipeline/builder.py)) :
- `PipelineBuilder`, `LLMBuilder`, `PhasesBuilder` — l'API publique de configuration

**Segmentator** ([segmentation/segmentator.py](src/ebook_translator/segmentation/segmentator.py)) :
- Découpe le contenu en segments bornés en tokens, avec contexte head/body/tail
- `overlap_ratio` inférieur à 1.0 = pourcentage, supérieur ou égal à 1.0 = multiple de `max_tokens`

**ValidationWorkerPool** ([validation/](src/ebook_translator/validation/)) :
- N threads `ValidationWorker` + 1 `SaveWorker` ; la classe de worker est choisie par phase (`UnifiedValidationWorker` avec checks de contenu, `SchemaOnlyValidationWorker` sans)
- Le découplage validation/sauvegarde garde les workers hors du chemin d'I/O disque
- Un check en échec déclenche une correction LLM ciblée ; les lignes irrécupérables sont abandonnées plutôt que de rejeter le chunk entier

**Client LLM** ([llm/llm.py](src/ebook_translator/llm/llm.py)) :
- Client compatible OpenAI, retry automatique avec backoff exponentiel
- Sortie structurée via Instructor pour les phases JSON
- Logging contextuel avec création de fichier différée

**Checks de contenu** ([checks/content/](src/ebook_translator/checks/content/)) :
- `LineCountCheck` : vérifie que toutes les lignes sont traduites
- `FragmentCountCheck` : vérifie le nombre de séparateurs `</>`
- `PunctuationCheck` : vérifie l'équilibre des paires de guillemets
- `SentenceCheck` : vérifie l'intégrité des phrases

**Persistance** ([persistence/](src/ebook_translator/persistence/), [stores/](src/ebook_translator/stores/)) :
- `ByteStore` pour l'I/O atomique brute, `ChunkPersister` pour la forme du cache, `PhaseStorage` pour les lier

### Architecture des templates

Les templates Jinja2 vivent dans le submodule `template/`. Chaque prompt est une **paire** de fichiers — `<nom>_system.jinja` et `<nom>_user.jinja` — résolus ensemble par les enums `PhaseTemplate` et `RetryTemplate`.

```
template/
├── common/     # fragments partagés, inclus via {% include %}
├── phase/      # prompts de phase (translate_base, translate_refine, analyze_chapter*, glossary)
└── retry/      # prompts de correction, un par type d'erreur
```

### Structure du projet

```
ebook-translator/
├── src/ebook_translator/
│   ├── checks/              # Protocole ContentCheck + implémentations content/
│   ├── exporter/            # Export Markdown des analyses et du glossaire
│   ├── glossary.py          # Glossaire pour la cohérence terminologique
│   ├── htmlpage/            # Parsing HTML et remplacement de texte
│   ├── llm/                 # Client LLM, providers, renderers, registre de retry
│   ├── persistence/         # Implémentations de ChunkPersister
│   ├── pipeline/            # Pipeline, phases, executor, builders, stockage
│   ├── segmentation/        # Segmentator, Chunk, détection de chapitres
│   ├── stores/              # ByteStore / Store
│   ├── translation/         # I/O EPUB
│   └── validation/          # Pool, worker unifié, save worker, helpers de retry
├── src/template/            # Templates Jinja2 des prompts (submodule)
├── examples/                # Exemples exécutables
├── tests/                   # Tests unitaires (374 tests)
├── docs/                    # Documentation spécialisée
└── logs/                    # Logs de traduction, un répertoire par session
    └── run_YYYYMMDD_HHMMSS/
```

Pour plus de détails, consultez la documentation complète dans [docs/](docs/) ou [CLAUDE.md](CLAUDE.md).

## Documentation

| Document | Description |
|----------|-------------|
| **[CLAUDE.md](CLAUDE.md)** | Vue d'ensemble et démarrage rapide |
| **[docs/SETUP.md](docs/SETUP.md)** | Configuration, installation, dépannage |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Architecture technique, composants |
| **[docs/LITERARY_ANALYSIS.md](docs/LITERARY_ANALYSIS.md)** | Phase 0 et le schéma `AnalyseChapter` |
| **[docs/VALIDATION.md](docs/VALIDATION.md)** | Système de validation, checks, registre de retry |
| **[docs/TEMPLATES.md](docs/TEMPLATES.md)** | Architecture des templates LLM |
| **[docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md)** | Typage, docstrings, tests |
| **[docs/CHANGELOG.md](docs/CHANGELOG.md)** | Historique des versions (à partir de 0.12.0) |
| **[docs/CHANGELOG_ARCHIVE.md](docs/CHANGELOG_ARCHIVE.md)** | Historique des versions 0.2.0 → 0.11.0 |
| **[docs/ROADMAP.md](docs/ROADMAP.md)** | Fonctionnalités planifiées |
| **[docs/TECHNICAL_DEBT.md](docs/TECHNICAL_DEBT.md)** | Dette technique identifiée, laissée de côté sciemment |

## Sécurité

**IMPORTANT** :
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
