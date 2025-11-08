# Architecture du système

Ce document décrit l'architecture globale du traducteur d'ebooks.

## Vue d'ensemble

Le système est organisé en **architecture modulaire par phases** avec un orchestrateur central (`Pipeline`) qui coordonne l'exécution séquentielle des phases de traduction et des transitions entre celles-ci.

**Principes clés** :
- **Modularité** : Chaque phase est indépendante et réutilisable
- **Extensibilité** : Ajout facile de nouvelles phases ou transitions
- **Validation rigoureuse** : Système de checks avec retry progressif
- **Performance** : Découplage validation/sauvegarde pour +33-50% de throughput
- **Traçabilité** : Logging par session avec nommage contextuel

## Pipeline de traduction principal

Le processus de traduction suit ce flux orchestré par `Pipeline` :

```
EPUB Input (epub_handler)
    ↓
[Pipeline] orchestrate:
    ↓
Phase 1: Initial Translation (chunks 2000 tokens)
    ├─ [Segmentator] → Chunks (head/body/tail)
    ├─ [ValidationWorkerPool]
    │   ├─ [ValidationWorkers (N threads)]
    │   │   ├─ [Engine] → build_translation_map
    │   │   ├─ [LLM] → query API
    │   │   ├─ [Parser] → parse output
    │   │   ├─ [ValidationPipeline] → run checks
    │   │   └─ Submit to SaveQueue
    │   └─ [SaveWorker (1 thread)] → [StoreManager]
    ↓
[Transition: Glossary Validation]
    ├─ Extract glossary from Phase 1
    ├─ Filter conflicts
    └─ Prepare for Phase 2
    ↓
Phase 2: Refinement (chunks 300 tokens, with glossary)
    └─ Same workflow with glossary context
    ↓
[HtmlPage] → Text Replacement in DOM
    ↓
[epub_handler] → Reconstruct EPUB
    ↓
EPUB Output
```

**Flux détaillé** :
1. **Chargement EPUB** - Extraction métadonnées et contenu HTML
2. **Phase 1: Initial Translation** - Traduction par chunks de 2000 tokens
3. **Transition: Glossary Validation** - Extraction glossaire, filtrage conflits
4. **Phase 2: Refinement** - Raffinage avec glossaire (chunks 300 tokens)
5. **Reconstruction** - Remplacement texte dans DOM HTML
6. **Génération EPUB** - Création du fichier traduit final

## Architecture Pipeline

### Pipeline (orchestrateur principal)

**Fichier** : [pipeline/pipeline.py](../src/ebook_translator/pipeline/pipeline.py)

**Responsabilités** :
- Orchestration séquentielle des phases et transitions
- Initialisation du contexte global (PhaseContext)
- Gestion du cycle de vie des phases
- Coordination entre StoreManager et phases

**Méthode principale** :
```python
@staticmethod
def run(
    epub_htmls: list[HtmlPage],
    llm: LLM,
    target_language: str,
    store_manager: StoreManager,
    phases: list[PhaseBase],
    transitions: list[TransitionBase] = []
) -> tuple[dict, dict]:
    # Orchestrates phase execution + transitions
```

### PhaseBase (classe de base des phases)

**Fichier** : [pipeline/base.py](../src/ebook_translator/pipeline/base.py)

**Responsabilités** :
- Interface commune pour toutes les phases
- Définit le contrat : `execute()`, `get_name()`, `get_execution_mode()`
- Support de 3 modes d'exécution : PARALLEL, SEQUENTIAL, CUSTOM

**Phases concrètes** :
- **InitialTranslation** ([pipeline/phases/initial_translation.py](../src/ebook_translator/pipeline/phases/initial_translation.py))
  - Traduction initiale par chunks de 2000 tokens
  - Exécution parallèle (PARALLEL mode)
  - Pas de glossaire

- **Refinement** ([pipeline/phases/refinement.py](../src/ebook_translator/pipeline/phases/refinement.py))
  - Raffinage avec glossaire
  - Chunks de 300 tokens pour précision
  - Utilise glossaire extrait de Phase 1

### PhaseExecutor

**Fichier** : [pipeline/executor.py](../src/ebook_translator/pipeline/executor.py)

**Responsabilités** :
- Exécution concrète d'une phase
- Segmentation du contenu en chunks
- Soumission des chunks au ValidationWorkerPool
- Collecte des résultats et statistiques

**Workflow** :
1. Segmente le contenu via Segmentator
2. Initialise ValidationWorkerPool
3. Soumet chaque chunk au pool
4. Attend la complétion et collecte résultats
5. Retourne PhaseStats (temps, chunks traités, erreurs)

### StoreManager (gestion des caches)

**Fichier** : [pipeline/store_manager.py](../src/ebook_translator/pipeline/store_manager.py)

**Responsabilités** :
- Gestion centralisée des caches MultiStore
- Création/récupération de stores par phase
- Coordination entre phases pour partage de données

**Stores gérés** :
- `initial_translation` : Cache Phase 1
- `refinement` : Cache Phase 2
- Possibilité d'ajouter d'autres phases

## Système de Transition

**Fichier** : [transition/base.py](../src/ebook_translator/transition/base.py)

**Responsabilités** :
- Interface pour transitions entre phases
- Permet de transformer/enrichir le contexte
- Exécutées entre deux phases

**Transition concrète** :
- **GlossaryValidationTransition** ([transition/transitions/glossary_validation.py](../src/ebook_translator/transition/transitions/glossary_validation.py))
  - Extrait le glossaire de Phase 1
  - Filtre les conflits avec `glossary_filters.py`
  - Injecte le glossaire dans le contexte pour Phase 2

## Composants clés

### Segmentator

**Fichier** : [segmentation/segmentator.py](../src/ebook_translator/segmentation/segmentator.py)

**Responsabilités** :
- Découpe le contenu en chunks basés sur tokens (tiktoken)
- Maintient chevauchement configurable (overlap_ratio)
- Suit quelles pages HTML appartiennent à chaque chunk (file_range)
- Préserve structure HTML (head/body/tail dans Chunk dataclass)

**Caractéristiques avancées** :
- Support `overlap_ratio >= 1.0` pour contexte étendu
- Système de queue pour gestion multi-chunks
- Warning automatique si overlap élevé (impact tokens)

**Dataclass Chunk** : [segmentation/chunk.py](../src/ebook_translator/segmentation/chunk.py)

### HtmlPage

**Fichier** : [htmlpage/page.py](../src/ebook_translator/htmlpage/page.py)

**Responsabilités** :
- Pattern singleton avec `pages_cache` pour éviter re-parsing
- Extrait texte des balises "p" et "h1" (voir `valid_root`)
- Regroupe fragments de texte par balise parente
- Gère séparateurs de fragments `</>`
- `replace_text()` pour remplacements simples et multi-fragments

**Composants associés** :
- **TagKey** ([htmlpage/tag_key.py](../src/ebook_translator/htmlpage/tag_key.py)) : Wrapper pour clés de cache
- **TextReplacer** ([htmlpage/replacement.py](../src/ebook_translator/htmlpage/replacement.py)) : Logique de remplacement

**Pattern de séparateur** :
- Fragments multiples dans même balise parente joints avec `</>`
- Exemple : `["Hello ", "world"]` → `"Hello</>world"`
- Traduction doit préserver ce séparateur pour reconstruction correcte

### LLM (Client API)

**Fichier** : [llm/llm.py](../src/ebook_translator/llm/llm.py)

**Responsabilités** :
- Client async OpenAI pour toute API compatible OpenAI
- Templates Jinja2 du répertoire `template/` pour prompts
- Logs individuels pour chaque requête dans `logs/`
- Pattern callback avec `on_response` pour streaming

**Fonctionnalités avancées** :
- Retry automatique avec backoff exponentiel (v0.3.0)
- Support mode reasoning (`deepseek-reasoner`) pour corrections complexes (v0.8.0)
- Température optimisée à 0.5 pour cohérence (v0.4.0)
- Logging contextuel par session avec création lazy (v0.6.0)

**Composants associés** :
- **TemplateRenderers** ([llm/template_renderers.py](../src/ebook_translator/llm/template_renderers.py)) : Rendu templates Jinja2
- **TemplateParams** ([llm/template_params.py](../src/ebook_translator/llm/template_params.py)) : Paramètres templates

### Engine (Traduction)

**Fichier** : [translation/engine.py](../src/ebook_translator/translation/engine.py)

**Responsabilités** :
- `build_translation_map()` : Construit mapping texte original → requête LLM
- `apply_translations()` : Applique traductions dans HtmlPage
- Gère le cycle complet traduction → validation → application

**Workflow** :
1. Extrait textes à traduire depuis HtmlPage
2. Envoie requêtes LLM via `llm.query()`
3. Parse la sortie LLM via Parser
4. Valide les traductions via ValidationPipeline
5. Applique les traductions dans HtmlPage

### Parser

**Fichier** : [translation/parser.py](../src/ebook_translator/translation/parser.py)

**Responsabilités** :
- Parse la sortie LLM (format avec `<N/>`, `</>`, `[=[END]=]`)
- Validation du format (marqueur END, numérotation, structure)
- Détection erreurs LLM (messages `[ERREUR`)
- Extraction des traductions ligne par ligne

**Validations** :
- Présence du marqueur `[=[END]=]`
- Format numéroté correct (`<0/>`, `<1/>`, etc.)
- Nombre de lignes cohérent avec l'original

### EpubHandler (Gestion EPUB)

**Fichier** : [translation/epub_handler.py](../src/ebook_translator/translation/epub_handler.py)

**Responsabilités** :
- Extraction métadonnées EPUB (titre, auteur, langue, identifiant)
- Lecture spine order pour préserver ordre des chapitres
- Copie des ressources non-documents (images, CSS)
- Reconstruction EPUB traduit avec métadonnées préservées

### ValidationWorkerPool

**Fichier** : [validation/validation_worker_pool.py](../src/ebook_translator/validation/validation_worker_pool.py)

**Responsabilités** :
- Orchestre N ValidationWorkers + 1 SaveWorker
- Gère cycle de vie des threads
- Coordonne validation et sauvegarde

**Architecture multi-thread** :
```
ValidationQueue → ValidationWorkers (N threads, CPU-bound)
               ↓
            SaveQueue → SaveWorker (1 thread, I/O-bound)
                     ↓
                   StoreManager
```

**Composants** :
- **ValidationWorker** ([validation/validation_worker.py](../src/ebook_translator/validation/validation_worker.py))
  - Valide traductions (multi-thread, CPU-bound)
  - Exécute ValidationPipeline
  - Transmet chunks validés à SaveQueue

- **SaveWorker** ([validation/save_worker.py](../src/ebook_translator/validation/save_worker.py))
  - Pipeline I/O dédié pour découpler validation et persistance
  - Garantit ordre FIFO des sauvegardes
  - Exécute callbacks après sauvegarde confirmée

- **ValidationQueue / SaveQueue** ([validation/validation_queue.py](../src/ebook_translator/validation/validation_queue.py))
  - Queues thread-safe pour coordination
  - Gestion de la backpressure (limite utilisation mémoire)

**Bénéfices de SaveWorker** :
- **Performance** : ValidationWorkers ne bloquent pas sur écritures disque
- **Ordre déterministe** : Sauvegardes FIFO (facilite debug)
- **Callbacks thread-safe** : Exécutés après confirmation sauvegarde
- **Gestion erreurs centralisée** : Logs cohérents, statistiques unifiées

### ValidationPipeline (Checks)

**Fichier** : [checks/pipeline.py](../src/ebook_translator/checks/pipeline.py)

**Responsabilités** :
- Exécute séquentiellement les checks de validation
- Collecte les erreurs détectées
- Déclenche corrections avec retry progressif si erreurs

**Checks disponibles** :
- **LineCountCheck** ([checks/check_tests/line_count_check.py](../src/ebook_translator/checks/check_tests/line_count_check.py))
  - Vérifie que toutes les lignes sont traduites

- **FragmentCountCheck** ([checks/check_tests/fragment_count_check.py](../src/ebook_translator/checks/check_tests/fragment_count_check.py))
  - Vérifie nombre de séparateurs `</>` préservé

- **PunctuationCheck** ([checks/check_tests/punctuation_check.py](../src/ebook_translator/checks/check_tests/punctuation_check.py))
  - Vérifie équilibre des paires de guillemets

- **SentenceCheck** ([checks/check_tests/sentence_check.py](../src/ebook_translator/checks/check_tests/sentence_check.py))
  - Vérifie intégrité des phrases

**Retry progressif** (v0.8.0) :
- Tentative 1 : Mode normal (`deepseek-chat`) via [checks/retry_helper.py](../src/ebook_translator/checks/retry_helper.py)
- Tentative 2 : Mode reasoning (`deepseek-reasoner`)
- **Impact** : +10-20% taux de succès, -40% chunks filtrés

## Système de Stores

### Store (Cache persistant)

**Fichier** : [stores/store.py](../src/ebook_translator/stores/store.py)

**Responsabilités** :
- Cache thread-safe avec verrous par fichier
- Écriture atomique via fichier temporaire + rename
- Gestion robuste erreurs I/O (corruption, permissions Windows)
- Format JSON pour persistance

**Méthodes** :
- `save(key, value)` : Sauvegarde atomique
- `get(key)` : Récupération avec fallback
- `clear()` : Nettoyage du cache

### MultiStore (Gestion multi-caches)

**Fichier** : [stores/multi_store.py](../src/ebook_translator/stores/multi_store.py)

**Responsabilités** :
- Gestion de plusieurs stores simultanément
- Isolation des caches par phase
- Partage de données entre phases si nécessaire

## Modules complémentaires

### Glossary (Glossaire automatique)

**Fichiers** :
- [glossary.py](../src/ebook_translator/glossary.py) : Système de glossaire automatique
- [glossary_filters.py](../src/ebook_translator/glossary_filters.py) : Filtrage conflits

**Responsabilités** :
- Apprentissage automatique des traductions (noms propres, termes techniques)
- Détection conflits (même terme → traductions différentes)
- Persistance sur disque (JSON)
- Validation manuelle possible (prioritaire sur apprentissage)

### Configuration

**Fichiers** :
- [config.py](../src/ebook_translator/config.py) : Constantes de templates, chemins
- [constants.py](../src/ebook_translator/constants.py) : Constantes globales

**Responsabilités** :
- Centralisation de la configuration
- Noms de templates (TRANSLATE, CORRECT)
- Chemins vers ressources

### Logger (Logging par session)

**Fichier** : [logger.py](../src/ebook_translator/logger.py)

**Responsabilités** :
- Classe `LogSession` (singleton) gérant répertoire unique par exécution
- Classe `LazyFileHandler` créant fichier au premier log (évite fichiers vides)
- Helper `get_session_log_path()` pour chemins contextuels

**Organisation par session** :
```
logs/
├── run_20251023_143022/          # Session d'exécution
│   ├── translation.log            # Log principal
│   ├── llm_chunk_001_0001.log    # Requête LLM chunk 1
│   ├── llm_retry_chunk_005_attempt_1_0003.log  # Retry
│   └── llm_correction_XXX_0004.log  # Correction
└── run_20251023_150145/          # Session suivante
```

**Nommage contextuel** :
- `llm_chunk_XXX_XXXX.log` : Traduction chunk
- `llm_retry_chunk_XXX_attempt_X_XXXX.log` : Retry chunk
- `llm_correction_XXX_XXXX.log` : Correction structurelle
- Création lazy (fichier créé seulement si réponse LLM)

### Language (Enum langues)

**Fichier** : [translation/language.py](../src/ebook_translator/translation/language.py)

**Responsabilités** :
- Enum des langues supportées
- Codes ISO (ex: "fr", "en", "es")

## Flux de données

### Extraction de texte

L'extraction utilise un pattern de séparateur spécial :
- Fragments multiples dans même balise parente joints avec `</>`
- Exemple : `["Hello ", "world"]` → `"Hello</>world"`
- Traduction doit préserver ce séparateur pour reconstruction correcte

### Format de traduction

**Balises de numérotation `<N/>`** :
- Chaque ligne commence par `<0/>`, `<1/>`, etc.
- OBLIGATOIRE : Reproduire EXACTEMENT dans la traduction
- INTERDICTION : Modifier, supprimer, ajouter des numéros

**Séparateurs de fragments `</>`** :
- Marquent fragments multiples dans une même balise HTML
- OBLIGATOIRE : Préserver EXACTEMENT le même nombre
- Exemple : `<0/>Hello</>world` → `<0/>Bonjour</>monde`

**Marqueur de fin** :
- Toutes les traductions se terminent par `[=[END]=]`
- Utilisé pour validation de complétude

## Configuration

### Paramètres du système

- **Sélection du modèle** : Passer `model_name` à LLM (défaut : "deepseek-chat")
- **Concurrence** : Paramètre `num_workers` dans ValidationWorkerPool
- **Langue cible** : Code ISO via Language enum
- **Templates** : Répertoire `template/` (templates Jinja2 `.jinja`)
- **Overlap** : `overlap_ratio` dans Segmentator (défaut : 0.15 = 15%)
- **Température LLM** : Contrôle déterminisme (défaut : 0.5)

### Variables d'environnement

| Variable | Obligatoire | Défaut | Description |
|----------|-------------|--------|-------------|
| `DEEPSEEK_API_KEY` | ✅ Oui | - | Clé API DeepSeek pour authentification |
| `DEEPSEEK_URL` | ❌ Non | `https://api.deepseek.com` | URL de base API DeepSeek |
| `OPENAI_API_KEY` | ❌ Non | - | Clé API OpenAI (alternative à DeepSeek) |

## Notes importantes d'implémentation

### Préservation de l'ordre du spine

La lecture EPUB maintient l'ordre du spine via liste `spine_order` pour garantir que chapitres apparaissent correctement.

### Copie des métadonnées

Titre, identifiant, langue et auteurs préservés depuis EPUB source.

### Gestion des ressources

Éléments non-documents (images, CSS) copiés sans modification.

### Gestion des erreurs

Erreurs LLM capturées et enregistrées comme "[ERREUR DE REQUÊTE]" dans fichiers de log.

#### Système de retry

**Retry automatique** :
- `APITimeoutError` : Backoff ×2 (1s, 2s, 4s)
- `RateLimitError` : Backoff ×3 (1s, 3s, 9s)
- Max 3 tentatives par défaut

**Retry progressif** (v0.8.0) :
- Tentative 1 : Mode normal (`deepseek-chat`)
- Tentative 2 : Mode reasoning (`deepseek-reasoner`)
- Utilisé pour corrections structurelles complexes

## Architecture des templates

### Catégorisation

**TRANSLATE Templates** - Créent nouvelles traductions :
- `translate_base.jinja` : Phase 1 - Traduction initiale (chunks 2000 tokens)
- `translate_refine.jinja` : Phase 2 - Raffinage avec glossaire (chunks 300 tokens)
- `retry_translate_missing_lines_targeted.jinja` : Retraduire lignes spécifiques ignorées
- `retry_translate_sentence.jinja` : Retraduire segments tronqués par LLM

**CORRECT Templates** - Corrigent erreurs structurelles :
- `retry_correct_fragments.jinja` : Corriger nombre `</>` (positions exactes)
- `retry_correct_fragments_flexible.jinja` : Corriger nombre `</>` (positions flexibles)
- `retry_correct_punctuation.jinja` : Corriger paires de guillemets

### Bases communes (v0.9.0)

**common_translate_rules.jinja** (199 lignes) :
- Règles générales de traduction (fidélité, style, cohérence)
- Gestion des balises `<N/>` et `</>`
- Exemples few-shot learning (4 exemples complets)
- Format de sortie standard

**common_correct_rules.jinja** (130 lignes) :
- Philosophie de correction (minimiser changements, préserver sens)
- Gestion des balises (focus comptage exact)
- Checklist de vérification finale
- Format de sortie

**Bénéfices** :
- -73% duplication de code
- 7× plus facile à maintenir (1 fichier au lieu de 7)
- Cohérence 100% garantie

## Point d'entrée

**Fichier** : [example_pipeline.py](../example_pipeline.py)

**Exemple d'utilisation** :
```python
from ebook_translator.pipeline import Pipeline
from ebook_translator.pipeline.phases import InitialTranslation, Refinement
from ebook_translator.transition.transitions import GlossaryValidationTransition

# Configuration
phases = [
    InitialTranslation(llm, target_language="fr", max_tokens=2000),
    Refinement(llm, target_language="fr", max_tokens=300)
]

transitions = [
    GlossaryValidationTransition()  # Entre Phase 1 et Phase 2
]

# Exécution
translation_map, glossary = Pipeline.run(
    epub_htmls=htmls,
    llm=llm,
    target_language="fr",
    store_manager=store_manager,
    phases=phases,
    transitions=transitions
)
```

## Voir aussi

- [VALIDATION.md](VALIDATION.md) - Architecture de validation détaillée
- [TEMPLATES.md](TEMPLATES.md) - Architecture des templates LLM
- [ROADMAP.md](ROADMAP.md) - Améliorations futures planifiées
- [CHANGELOG.md](CHANGELOG.md) - Historique des versions (0.2.0 → 0.9.0)
