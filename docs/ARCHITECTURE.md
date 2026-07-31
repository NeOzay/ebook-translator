# Architecture du système

## Vue d'ensemble

Le système est organisé en **pipeline modulaire par phases** orchestré par `Pipeline` ([pipeline/pipeline.py](../src/ebook_translator/pipeline/pipeline.py)). Chaque phase est un plugin indépendant héritant de `PhaseBase`.

**Flux principal** :
```
EPUB Input
  → [Phase 0] Analyse littéraire (optionnelle, séquentielle)
  → [Phase Glossaire] Extraction des termes (optionnelle, séquentielle)
  → [Phase 1] Traduction initiale (parallèle)
  → [Phase 2] Raffinage (séquentielle)
  → EPUB Output
```

L'ordre est celui de la liste passée à `Pipeline(phases=[...])` ; toutes les phases sont facultatives sauf les dépendances déclarées (`depends_on`), vérifiées au démarrage par `_validate_dependencies()`.

Deux abstractions structurent tout le reste :

- **`M` (payload)** — modèle Pydantic qui valide la **forme** de la sortie LLM.
- **`DT` (data)** — vue `TypedDict` qui circule dans les queues et le cache. `M.build()` produit `DT` ; la conversion n'est pas réversible, donc le Pydantic est abandonné dès l'executor.

---

## API publique : les builders

**Fichier** : [pipeline/builder.py](../src/ebook_translator/pipeline/builder.py)

Trois builders chaînables couvrent la configuration complète :

```python
stats = (
    PipelineBuilder()
    .epub("input.epub")
    .output("output.epub")
    .language(Language.FRENCH)
    .llm(LLMBuilder().default_client(Deepseek(DeepseekModels.FLASH, thinking=False)))
    .phases(
        PhasesBuilder()
        .add_literary_analysis()
        .add_initial_translation(max_tokens=2000)
        .add_refinement()
    )
    .workers(4)
    .run()
)
```

- `LLMBuilder` — porte les options de `LLM` (`prompt_dir`, `max_retries`, `retry_delay`, `glossary_max_terms`). Le **modèle, le mode thinking et la température appartiennent au client** (`.default_client(...)`) : `base_url` est un attribut de classe du provider et chaque provider expose sa propre enum de modèles.
- `PhasesBuilder` — `add_literary_analysis()`, `add_glossary_generation()`, `add_initial_translation()`, `add_refinement()`. Chaque `add_*` accepte des overrides (`max_tokens`, `overlap_ratio`, `max_workers`, `llm_config`) ; les valeurs omises retombent sur les defaults de la phase.
- `PipelineBuilder` — `.build()` retourne `(pipeline, run_kwargs)`, `.run()` enchaîne directement.

---

## Pipeline et phases

### Pipeline

**Fichier** : [pipeline/pipeline.py](../src/ebook_translator/pipeline/pipeline.py)

Orchestrateur principal. Charge l'EPUB, initialise l'infrastructure partagée (`StoreManager`, `Glossary`, `ValidationWorkerPool`, `CommunContext`), exécute les phases dans l'ordre via un `PhaseExecutor`, puis reconstruit et écrit l'EPUB final.

Le cache par défaut est `<dossier_epub>/.<nom_epub>_cache/` ; le glossaire est sauvegardé en fin de run dans `<dossier_epub>/.<nom_epub>_glossary.json`.

### PhaseBase

**Fichier** : [pipeline/base.py](../src/ebook_translator/pipeline/base.py)

Base générique `PhaseBase[ChunkType, DT, M]`. Une phase déclare :

| Attribut | Rôle |
|---|---|
| `name` | Membre de `PhaseName` — sert aussi de clé de cache (`store_key()`) |
| `execution_mode` | `PARALLEL` ou `SEQUENTIAL` |
| `max_tokens`, `overlap_ratio`, `head_tail_balance` | Paramètres de segmentation |
| `chunk_type` | Type de chunk attendu — vérifié à l'exécution par l'executor |
| `payload_type` | Modèle Pydantic `M` validant la sortie LLM |
| `data_type` | Vue `TypedDict` `DT` circulant en queue et en cache |
| `content_checks` | Tuple de `ContentCheck` appliqués après validation du schéma |
| `persister` | `ChunkPersister` déterminant la forme du cache |
| `depends_on` | Phases dont les sorties sont nécessaires en entrée |

Méthodes principales : `render_prompt()` (abstraite) → `(system, user)`, `get_llm_config()` → `LLMConfig | JsonRequestConfig`, `get_chunks()`, `get_translation_cache()`, `save_item_builder()`, et les hooks `before_phase()` / `before_chunk()` / `after_response()` / `on_save()` / `after_phase()`.

Deux hooks encadrent la validation, et le choix entre les deux n'est pas anodin :

| Hook | Thread | Donnée reçue | Échec |
|------|--------|--------------|-------|
| `after_response(chunk, data, context)` | executor | sortie LLM validée par le schéma, **avant** les `content_checks` | remonte, le chunk échoue |
| `on_save(chunk, data)` | `SaveWorker` | donnée validée **et** persistée | logué en warning, absorbé |

`after_response` est synchrone : ce qu'il modifie est visible du chunk suivant. `on_save` est asynchrone — l'executor peut rendre le prompt du chunk N+1 avant que le `SaveWorker` ait traité le chunk N. Un effet de bord que la phase doit voir immédiatement va dans `after_response` ; un export de revue va dans `on_save`.

`PhaseProtocol` est l'interface structurelle que consomment l'executor et les workers, sans dépendre de `PhaseBase`.

### PhaseExecutor

**Fichier** : [pipeline/executor.py](../src/ebook_translator/pipeline/executor.py)

Exécute une phase :

1. Hook `before_phase()`, puis `phase.get_chunks()` (type vérifié contre `chunk_type`)
2. `validation_pool.switch_phase(phase)` — reconfigure les workers
3. Pour chaque chunk : consulte le cache (`get_translation_cache()`). Un chunk intégralement en cache est **re-soumis à la validation** sans appel LLM
4. Sinon : `render_prompt()` → appel LLM (voie texte ou voie Instructor selon `get_llm_config()`) → `payload_type.model_validate()` → `payload.build()` → `DT`
5. Soumet un `ValidationItem` au pool ; attend `wait_completion()`
6. Hook `after_phase(stats)` et retourne `PhaseStats`

Le mode parallèle (`ThreadPoolExecutor`) est retenu si `execution_mode == PARALLEL` **ou** si `get_worker_count() > 1`.

### Contextes

**Fichier** : [pipeline/context.py](../src/ebook_translator/pipeline/context.py)

- `CommunContext` — état global **gelé** (`FrozenStatic`, attributs `ClassVar`) : `llm`, `book`, `html_pages`, `chapters`, `glossary`, `store_manager`, `target_language`. Toute lecture avant `freeze()` lève ; les consommateurs y accèdent donc via `@property`.
- `PhaseContext` — ajoute `name`, `validation_pool`, `previous_phases`
- `ChunkContext` — ajoute `phase_name`, `chunk_index`, `previous_chunk`
- `PhaseStats` — métriques (`chunks_total/processed/from_cache/translated/validated/rejected`, `duration_seconds`, `rejection_rate`, `cache_hit_rate`)

---

## Phases concrètes

**Répertoire** : [pipeline/phases/](../src/ebook_translator/pipeline/phases/)

### Phase 0 — Analyse littéraire

**Fichier** : [pipeline/phases/literary_analysis.py](../src/ebook_translator/pipeline/phases/literary_analysis.py)

- Chunk : `ChapterPartChunk` — blocs de 5000 tokens, `overlap_ratio` figé à 0.0, 1 worker
- Séquentielle, sortie structurée via Instructor
- `payload_type` = `data_type` = `AnalyseChapter` (schéma stratifié, submodule `template`)
- `content_checks = ()` — la validation est intégralement portée par le schéma Pydantic
- Analyse **incrémentale** : chaque bloc reprend la fiche du bloc précédent et l'enrichit
- Expose `latest_analysis_for(chapter_name)`, injecté dans `Chapters` comme `AnalysisLookup`

Voir [LITERARY_ANALYSIS.md](LITERARY_ANALYSIS.md).

### Phase Glossaire

**Fichier** : [pipeline/phases/glossary.py](../src/ebook_translator/pipeline/phases/glossary.py)

- Chunk : `GlossaryChunk`, 2000 tokens, overlap 0.5, séquentielle, 1 worker
- `payload_type` = `LLMGlossaryModel`, `data_type` = `list[LLMTermeGlossary]`
- `content_checks = ()` — schéma seul
- Persistance mémoïsée sous le namespace `"glossary"` : les termes valent pour tout l'ouvrage

### Phase 1 — Traduction initiale

**Fichier** : [pipeline/phases/initial_translation.py](../src/ebook_translator/pipeline/phases/initial_translation.py)

- Chunks de 1500 tokens, overlap 0.15, `PARALLEL`, aucune dépendance
- `payload_type` = `LineIndexedLLMResponse`, `data_type` = `LineIndexed`
- Template `translate_base` ; quatre `content_checks` (voir [VALIDATION.md](VALIDATION.md))

### Phase 2 — Raffinage

**Fichier** : [pipeline/phases/refinement.py](../src/ebook_translator/pipeline/phases/refinement.py)

- Chunks de 300 tokens, overlap 1.0 (chaque chunk inclut le précédent en entier), `SEQUENTIAL`
- `depends_on = (InitialTranslationPhase,)`
- Template `translate_refine` (glossaire + traduction précédente) ; mêmes `content_checks` que Phase 1

`DummyPhase` ([phases/dummy_phase.py](../src/ebook_translator/pipeline/phases/dummy_phase.py)) est un placeholder servant à construire le `ValidationWorkerPool` avant le premier `switch_phase()`.

---

## Segmentation

### Segmentator

**Fichier** : [segmentation/segmentator.py](../src/ebook_translator/segmentation/segmentator.py)

Découpe les `EpubHtml` en `Chunk` (head/body/tail). Paramètres : `max_tokens` (via tiktoken) et `overlap_ratio` (< 1.0 = pourcentage, ≥ 1.0 = multiple de `max_tokens`).

- `get_all_segments()` → `Iterator[Chunk]` pour les phases de traduction
- `get_all_chapters_by_spine()` → chunks de chapitre pour Phase 0

### Chunk

**Fichier** : [segmentation/chunk.py](../src/ebook_translator/segmentation/chunk.py)

`ChunkProtocol` définit le contrat consommé par l'executor, les persisters et les checks ; `Chunk` en est l'implémentation de traduction.

- `head` / `body` / `tail` : contexte avant, contenu principal, contexte après
- `prepare_for_prompt(indices)` : sérialise en format numéroté `<N/>` pour le LLM, éventuellement restreint à certains indices (utilisé par les retries ciblés)
- `calculate_chunk_hash()` : empreinte servant de clé de cache
- `split_chunk()` : redécoupe si trop grand

`ChapterChunk` / `ChapterPartChunk` ([chapter_chunk.py](../src/ebook_translator/segmentation/chapter_chunk.py)) et `TranslatedChunk` ([translated_chunk.py](../src/ebook_translator/segmentation/translated_chunk.py)) couvrent les autres granularités.

### Chapitres

**Fichiers** : [segmentation/chapter.py](../src/ebook_translator/segmentation/chapter.py), [segmentation/chapter_detector.py](../src/ebook_translator/segmentation/chapter_detector.py)

`SequentialChapterDetector` parcourt le spine EPUB et reconstruit des `ChapterInfo` (plusieurs patterns de nommage, numérique / romain / textuel, français et anglais ; croisement avec la table des matières).

`Chapters` associe un chunk à son chapitre et donne accès à son analyse littéraire via `get_literary_analysis(chunk)`. Il reçoit un callable `AnalysisLookup` — **jamais** le `StoreManager` : la lecture du cache Phase 0 appartient à Phase 0.

---

## Client LLM et templates

### LLM

**Fichier** : [llm/llm.py](../src/ebook_translator/llm/llm.py)

Façade au-dessus d'un client provider (`ClientProviderProtocol`) :

- `query(system_prompt, content, log_name, config)` → texte
- `json_query(..., response_model)` → instance Pydantic via Instructor
- Retry réseau avec backoff exponentiel
- Un fichier de log par échange (`LazyFileHandler`)

Les clients concrets vivent dans [llm/clients/](../src/ebook_translator/llm/clients/) : `OpenAIClientBase` porte le transport et le logging, `Deepseek` la table des modèles (`deepseek-v4-flash`, `deepseek-v4-pro`) et la configuration du thinking mode.

### TemplateRenderer

**Fichier** : [llm/template_renderers.py](../src/ebook_translator/llm/template_renderers.py)

Charge et rend les templates Jinja2 du submodule `template/`. Chaque template est une **paire** `*_system.jinja` + `*_user.jinja`, résolue par les enums `PhaseTemplate` (préfixe `phase/`) et `RetryTemplate` (préfixe `retry/`).

Voir [TEMPLATES.md](TEMPLATES.md).

---

## Validation et sauvegarde

### ValidationWorkerPool

**Fichier** : [validation/validation_worker_pool.py](../src/ebook_translator/validation/validation_worker_pool.py)

```
ValidationQueue → N × ValidationWorker (CPU + appels LLM de correction)
                → SaveQueue → 1 × SaveWorker (I/O) → ByteStore
```

- `switch_phase(phase)` : reconfigure les workers pour la phase courante, ou les recycle si elle demande un autre type de worker
- `submit(ValidationItem)`, `wait_completion()`, `get_statistics()`

Le type de worker est choisi **par phase**, sur `phase.content_checks` : c'est le pool, et non le worker, qui sait quelle forme de donnée transite.

### ValidationWorker

**Fichier** : [validation/worker_base.py](../src/ebook_translator/validation/worker_base.py)

Socle commun : boucle de consommation de la `ValidationQueue`, passage au `SaveWorker` via `phase.save_item_builder()`, comptage et log. Les sous-classes ne fournissent que `_process()`, seul endroit qui connaît la forme de `DT`. Un `_process()` peut lever `RejectOutcome` : l'item part alors en rejet, sans sauvegarde.

### UnifiedValidationWorker

**Fichier** : [validation/unified_worker.py](../src/ebook_translator/validation/unified_worker.py)

Worker des phases **avec** `content_checks` — la donnée doit être un mapping line-indexed. Un seul worker pour toutes ces phases : aucune surcharge par phase, le routage des corrections passe entièrement par `RETRY_REGISTRY` et par les métadonnées portées par chaque `ContentCheck`.

Traitement **check par check** : les `phase.content_checks` sont parcourus dans l'ordre de déclaration, chacun épuisant son budget de retries sur ses propres échecs avant de passer la main. Aucune ré-évaluation des checks précédents. Si un échec survit à `max_attempts`, les indices concernés sont **droppés** et le chunk est sauvegardé partiel — un chunk avec trous vaut mieux qu'un chunk rejeté.

### SchemaOnlyValidationWorker

**Fichier** : [validation/schema_only_worker.py](../src/ebook_translator/validation/schema_only_worker.py)

Worker des phases **sans** `content_checks` (Phase 0, glossaire) : leur schéma Pydantic les valide entièrement côté executor. Passe-plat — la donnée traverse sans copie ni inspection, ce qui permet à `DT` d'être une `list` ou un `BaseModel` plutôt qu'un mapping line-indexed.

### SaveWorker

**Fichier** : [validation/save_worker.py](../src/ebook_translator/validation/save_worker.py)

Consomme `SaveQueue` en FIFO et délègue l'écriture au `ChunkPersister` porté par le `SaveItem`. Découple l'I/O de la validation ; exécute les callbacks `on_save` après confirmation d'écriture.

### ContentCheck

**Fichier** : [checks/content_check.py](../src/ebook_translator/checks/content_check.py)

Protocole : `run(data, source) → list[ValidationFailure]`, plus trois `ClassVar` — `error_type` (membre de `ErreursType`), `retry_strategy` et `max_attempts`. Le check **détecte** ; il ne corrige pas : la correction est produite par le registre de retry.

Implémentations dans [checks/content/](../src/ebook_translator/checks/content/) : `LineCountCheck`, `FragmentCountCheck`, `PunctuationCheck`, `SentenceCheck`.

### Registre de retry

**Fichier** : [llm/retry_registry.py](../src/ebook_translator/llm/retry_registry.py)

`RETRY_REGISTRY` associe chaque `ErreursType` à une `RetryEntry` : template de correction, `TypedDict` de paramètres, fonction `build` qui compose le prompt depuis le diagnostic typé, et un `mode` de fusion (`replace` pour les corrections mono-ligne, `merge` pour les corrections par lot).

`RetryStrategy` ([validation/retry_strategy.py](../src/ebook_translator/validation/retry_strategy.py)) décide du modèle employé selon la tentative : `NORMAL_ONLY`, `PROGRESSIVE_REASONING` (normal puis reasoning), `REASONING_ONLY`.

Les erreurs **de schéma** (`SCHEMA_LEVEL_ERRORS` : format invalide, marqueur de fin absent, indices dupliqués) ne donnent pas lieu à un retry ciblé — le prompt de phase complet est rejoué.

Voir [VALIDATION.md](VALIDATION.md).

---

## Persistance

Le cache est stratifié en trois couches, du plus bas au plus haut :

### ByteStore

**Fichier** : [stores/byte_store.py](../src/ebook_translator/stores/byte_store.py)

Protocole d'octets pur : `read`, `write`, `delete`, `exists`, `list_keys`, `lock`. `FileByteStore` en est l'implémentation disque — verrous par fichier au niveau module et écriture atomique (fichier temporaire + rename).

### ChunkPersister

**Répertoire** : [persistence/](../src/ebook_translator/persistence/)

Décide **ce qui** est écrit et **comment le relire** : `is_chunk_cached()`, `persist()`, `load_for_chunk()` (avec store de fallback optionnel pour la reprise inter-phases).

- `LineIndexedPersister` — un fichier par chunk, mapping `{index_de_ligne: texte}` (Phases 1 et 2)
- `MemoizedChunkPersister` — mémoïsation `outer_key` / `inner_key` via `TypeAdapter`, pour les payloads non ligne-à-ligne (Phase 0, glossaire)

### PhaseStorage

**Fichier** : [pipeline/phase_storage.py](../src/ebook_translator/pipeline/phase_storage.py)

Simple binder : compose un `ChunkPersister`, un `ByteStore` principal et un fallback. Expose `is_cached()`, `load()`, `persist()`, `save_item()`. Toute la logique de routage vit dans le persister.

### Store et StoreManager

**Fichiers** : [stores/store.py](../src/ebook_translator/stores/store.py), [pipeline/store_manager.py](../src/ebook_translator/pipeline/store_manager.py)

`StoreManager` crée un `Store` par phase sous `<cache_dir>/<store_key>/` et le fournit à la demande. `Store` est le dépositaire historique du cache JSON, avec chaînage de fallback inter-phases (`set_fallback`).

---

## Parsing HTML et reconstruction EPUB

### HtmlPage

**Fichier** : [htmlpage/page.py](../src/ebook_translator/htmlpage/page.py)

Singleton par `EpubHtml`. Extrait les fragments texte des balises et les indexe par `TagKey`. Les fragments multiples d'une même balise parente sont joints par `</>`.

- `dump()` → itérateur `(TagKey, texte)` numéroté
- `replace_text(...)` → applique les traductions dans le DOM
- `save()` → réinjecte le HTML modifié dans l'item EPUB

Le rendu bilingue est porté par [htmlpage/bilingual.py](../src/ebook_translator/htmlpage/bilingual.py) (`BilingualFormat`).

### EpubHandler

**Fichier** : [translation/epub_handler.py](../src/ebook_translator/translation/epub_handler.py)

- `extract_html_items_in_spine_order()` : items HTML dans l'ordre du spine
- `reconstruct_html_item(item)` : reconstruit un item après remplacement
- `copy_epub_metadata()` : préserve titre, auteur, langue, identifiant

---

## Glossaire

**Fichier** : [glossary.py](../src/ebook_translator/glossary.py)

Apprentissage automatique des traductions (noms propres, termes techniques) avec comptage de fréquences, score de confiance et de dominance. Détecte les conflits (même terme, traductions divergentes). Persistance JSON, import depuis un volume précédent avec décroissance. `add_user_translation()` marque un terme comme manuel, donc prioritaire.

L'export vers les prompts passe par [exporter/glossary_exporter.py](../src/ebook_translator/exporter/glossary_exporter.py) ; l'export Markdown des analyses par [exporter/analysis_exporter.py](../src/ebook_translator/exporter/analysis_exporter.py), dont les libellés sont validés contre le schéma à l'import.

---

## Logging

**Fichier** : [logger.py](../src/ebook_translator/logger.py)

Organisation par session : `logs/run_YYYYMMDD_HHMMSS/`. Chaque échange LLM produit un fichier de log individuel nommé par contexte (phase, index de chunk, tentative). `LazyFileHandler` ne crée le fichier qu'au premier enregistrement, ce qui évite les fichiers vides.

---

## Format des données LLM

**Source de vérité unique** : `LineIndexedLLMResponse` ([template/phase/translation_models.py](../src/template/phase/translation_models.py)). Le format n'est décrit et validé qu'à cet endroit.

- **Balises de numérotation** : chaque ligne commence par `<0/>`, `<1/>`, etc., reproduites exactement
- **Séparateur de fragments** : `</>` signale plusieurs fragments HTML dans la même balise parente ; nombre et position doivent être préservés
- **Marqueur de fin** : `[=[END]=]` en dernière ligne, utilisé pour valider la complétude

---

## Voir aussi

- [LITERARY_ANALYSIS.md](LITERARY_ANALYSIS.md) — Phase 0, schéma `AnalyseChapter`
- [VALIDATION.md](VALIDATION.md) — Checks, registre de retry, cycle du worker
- [TEMPLATES.md](TEMPLATES.md) — Architecture des templates Jinja2
- [CODING_STANDARDS.md](CODING_STANDARDS.md) — Standards de code
