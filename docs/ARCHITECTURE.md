# Architecture du système

## Vue d'ensemble

Le système est organisé en **pipeline modulaire par phases** orchestré par `Pipeline` ([pipeline/pipeline.py](../src/ebook_translator/pipeline/pipeline.py)). Chaque phase est un plugin indépendant héritant de `PhaseBase`.

**Flux principal** :
```
EPUB Input
  → [Phase 0] Analyse littéraire (optionnelle, séquentielle)
  → [Phase 1] Traduction initiale (parallèle)
  → [Transition] Validation glossaire (optionnelle)
  → [Phase 2] Raffinage (séquentielle)
  → EPUB Output
```

---

## Pipeline et phases

### Pipeline

**Fichier** : [pipeline/pipeline.py](../src/ebook_translator/pipeline/pipeline.py)

Orchestrateur principal. Initialise le contexte global (`PhaseContext`), instancie les composants partagés (StoreManager, Glossary, ValidationWorkerPool), exécute les phases séquentiellement avec leurs transitions, puis reconstruit et écrit l'EPUB final.

### PhaseBase

**Fichier** : [pipeline/base.py](../src/ebook_translator/pipeline/base.py)

Interface abstraite pour toutes les phases. Une phase déclare :
- `execution_mode` : PARALLEL ou SEQUENTIAL
- `max_tokens`, `overlap_ratio` : configuration de la segmentation
- `checks` : liste de `Check` pour valider les sorties LLM
- `depends_on` : phases dont les traductions sont nécessaires en entrée
- Hooks : `before_phase()`, `before_chunk()`, `after_chunk()`, `after_phase()`
- `render_prompt()` (abstract) : génère le prompt LLM pour un chunk

### PhaseExecutor

**Fichier** : [pipeline/executor.py](../src/ebook_translator/pipeline/executor.py)

Exécute concrètement une phase :
1. Segmente le contenu via `Segmentator`
2. Configure le `ValidationWorkerPool` pour la phase courante
3. Pour chaque chunk : vérifie le cache Store, sinon soumet à la validation pool
4. Attend la completion et retourne `PhaseStats`

### PhaseContext / ChunkContext

**Fichier** : [pipeline/context.py](../src/ebook_translator/pipeline/context.py)

Conteneurs de données injectés dans les phases :
- `PhaseContext` : données globales (target_language, html_items, llm, store_manager, validation_pool, glossary, chapters, previous_phases)
- `ChunkContext` : données par chunk (phase_name, chunk_index, llm, store_manager, glossary)
- `PhaseStats` : métriques d'exécution (chunks traités/cachés/traduits/validés/rejetés, durée)

### StoreManager

**Fichier** : [pipeline/store_manager.py](../src/ebook_translator/pipeline/store_manager.py)

Gère un `Store` par phase (à `cache/{phase_name}/`). Fournit `get_translate(phase, chunk)` et `get_with_fallback(chunk, phase_order)` pour la récupération avec fallback inter-phases.

---

## Phases concrètes

**Fichiers** : [pipeline/phases/](../src/ebook_translator/pipeline/phases/)

### Phase 0 — Analyse littéraire

**Fichier** : [pipeline/phases/literary_analysis.py](../src/ebook_translator/pipeline/phases/literary_analysis.py)

- Chunk type : `ChapterPartChunk` (un chunk par chapitre, max 8000 tokens)
- Exécution séquentielle, mode JSON LLM
- Template : `analyze_chapter_simplified.jinja`
- Output : `ContexteTraduction` JSON validé par `AnalysisValidator`
- Peuple automatiquement le `Glossary` avec les `proposition_traduction`

Voir [LITERARY_ANALYSIS.md](LITERARY_ANALYSIS.md) pour le détail.

### Phase 1 — Traduction initiale

**Fichier** : [pipeline/phases/initial_translation.py](../src/ebook_translator/pipeline/phases/initial_translation.py)

- Chunks de 1500 tokens, overlap 15%, exécution parallèle
- Template : `translate_base.jinja`
- Checks : `LineCountCheck`, `FragmentCountCheck`, `PunctuationCheck`, `SentenceCheck`
- Apprend les traductions dans le `Glossary`

### Phase 2 — Raffinage

**Fichier** : [pipeline/phases/refinement.py](../src/ebook_translator/pipeline/phases/refinement.py)

- Chunks de 300 tokens, overlap 100% (contexte complet), exécution séquentielle
- Dépend de Phase 1 (`depends_on = [InitialTranslationPhase]`)
- Template : `translate_refine.jinja` (inclut glossaire + traduction précédente)
- Mêmes checks que Phase 1

---

## Segmentation

### Segmentator

**Fichier** : [segmentation/segmentator.py](../src/ebook_translator/segmentation/segmentator.py)

Découpe les `EpubHtml` items en `Chunk` (head/body/tail). Paramètres :
- `max_tokens` : taille cible des chunks (via tiktoken)
- `overlap_ratio` : ratio de chevauchement (< 1.0 = pourcentage, ≥ 1.0 = multiple de max_tokens)

Méthodes principales :
- `get_all_segments()` → Iterator[Chunk] pour les phases de traduction
- `get_all_chapters_by_spine()` → Iterator[ChapterChunk] pour Phase 0

### Chunk

**Fichier** : [segmentation/chunk.py](../src/ebook_translator/chunk.py)

Dataclass représentant un segment de contenu :
- `head` / `body` / `tail` : contexte avant, contenu principal, contexte après
- `__str__()` : sérialise en format numéroté `<N/>text` pour le LLM
- `calculate_chunk_hash()` : empreinte pour le cache Store
- `split_chunk()` : découpe si trop grand

### SequentialChapterDetector

**Fichier** : [segmentation/chapter_detector.py](../src/ebook_translator/segmentation/chapter_detector.py)

Détecte les chapitres depuis le spine EPUB. Supporte plusieurs patterns de nommage ("Chapter 1", "Chapitre I", etc.).

---

## Client LLM et templates

### LLM

**Fichier** : [llm/llm.py](../src/ebook_translator/llm/llm.py)

Wrapper autour du SDK OpenAI :
- `query(prompt, source_content, log_name, config)` → réponse LLM
- Retry automatique avec backoff exponentiel (APITimeoutError × 2, RateLimitError × 3)
- Support du mode reasoning (`deepseek-reasoner`) via `LLMConfig`
- Support du JSON mode pour les sorties structurées (Phase 0)
- Logs individuels par requête via `LazyFileHandler`

### TemplateRenderer

**Fichier** : [llm/template_renderers.py](../src/ebook_translator/llm/template_renderers.py)

Charge et rend les templates Jinja2 depuis `template/`. Fournit des méthodes typées :
- `render_translate()` — Phase 1
- `render_refine()` — Phase 2
- `render_analyze_simplified()` — Phase 0

---

## Validation et sauvegarde

### ValidationWorkerPool

**Fichier** : [validation/validation_worker_pool.py](../src/ebook_translator/validation/validation_worker_pool.py)

Architecture multi-thread :
```
ValidationQueue → N × ValidationWorker (CPU-bound)
                → SaveQueue → 1 × SaveWorker (I/O-bound) → Store
```

- `switch_phase(phase, store)` : reconfigure les workers pour la phase courante
- `submit(ValidationItem)` : soumet un chunk à valider
- `wait_completion()` : attend que toutes les queues soient vidées

### ValidationWorker

**Fichier** : [validation/validation_worker.py](../src/ebook_translator/validation/validation_worker.py)

Consomme `ValidationQueue`. Pour chaque item :
1. Exécute `ValidationPipeline.validate_and_correct(context)`
2. Si succès → soumet `SaveItem` à `SaveQueue`
3. Si échec → log + incrémente rejected_count

### SaveWorker

**Fichier** : [validation/save_worker.py](../src/ebook_translator/validation/save_worker.py)

Consomme `SaveQueue`. Écrit dans `Store` en ordre FIFO. Exécute les callbacks `on_save` après confirmation. Découple I/O de la validation → +33-50% throughput.

### ValidationPipeline

**Fichier** : [checks/pipeline.py](../src/ebook_translator/checks/pipeline.py)

Exécute les `Check` séquentiellement. En cas d'erreur :
- Tentative 1 : correction via LLM normal (`deepseek-chat`)
- Tentative 2 : correction via LLM reasoning (`deepseek-reasoner`)

### Checks disponibles

**Répertoire** : [checks/check_tests/](../src/ebook_translator/checks/check_tests/)

| Check | Vérifie |
|-------|---------|
| `LineCountCheck` | Toutes les lignes sont traduites |
| `FragmentCountCheck` | Nombre de séparateurs `</>` préservé |
| `PunctuationCheck` | Équilibre des paires de guillemets |
| `SentenceCheck` | Intégrité des phrases |

Chaque check implémente `validate(context)` → `CheckResult` et `correct(context, error_data)` → translations corrigées.

---

## Stockage (Store)

**Fichier** : [stores/store.py](../src/ebook_translator/stores/store.py)

Cache persistant par phase à `cache/{phase_name}/`. Format JSON, un fichier par chunk (nommé par hash). Thread-safe : verrous par fichier + écriture atomique via fichier temporaire + rename.

---

## Parsing HTML et reconstruction EPUB

### HtmlPage

**Fichier** : [htmlpage/page.py](../src/ebook_translator/htmlpage/page.py)

Singleton par `EpubHtml`. Extrait les fragments texte des balises `<p>` et `<h1>`. Les fragments multiples dans une même balise parente sont joints avec `</>`.

- `dump()` → texte numéroté pour LLM
- `replace(translations)` → applique les traductions dans le DOM
- `dump_bilingue()` → format bilingue

### EpubHandler

**Fichier** : [translation/epub_handler.py](../src/ebook_translator/translation/epub_handler.py)

- `extract_html_items_in_spine_order()` : lit les items HTML dans l'ordre du spine
- `reconstruct_html_item(item)` : reconstruit un item HTML après remplacement
- `copy_epub_metadata()` : préserve titre, auteur, langue, identifiant

### Parser

**Fichier** : [translation/parser.py](../src/ebook_translator/translation/parser.py)

Parse la sortie LLM (format `<N/>text`, séparateur `</>`, marqueur `[=[END]=]`) → `dict[int, str]`. Valide la complétude et la cohérence structurelle.

---

## Glossaire

**Fichier** : [glossary.py](../src/ebook_translator/glossary.py)

Apprentissage automatique des traductions (noms propres, termes techniques) avec comptage de fréquences. Détecte et signale les conflits (même terme, traductions différentes). Persistance JSON. La méthode `validate_translation()` marque un terme comme manuel (prioritaire).

---

## Logging

**Fichier** : [logger.py](../src/ebook_translator/logger.py)

Organisation par session : `logs/run_YYYYMMDD_HHMMSS/`. Chaque requête LLM génère un fichier de log individuel (nommage contextuel : chunk index, phase, tentative). Utilise `LazyFileHandler` : le fichier n'est créé qu'au premier log (évite les fichiers vides).

---

## Format des données LLM

**Balises de numérotation** : chaque ligne commence par `<0/>`, `<1/>`, etc. Le LLM doit les reproduire exactement.

**Séparateur de fragments** : `</>` dans une ligne signale des fragments HTML multiples dans la même balise parente. Doit être préservé en nombre et position.

**Marqueur de fin** : `[=[END]=]` en dernière ligne, utilisé pour valider la complétude.

---

## Voir aussi

- [LITERARY_ANALYSIS.md](LITERARY_ANALYSIS.md) — Phase 0, schéma ContexteTraduction
- [VALIDATION.md](VALIDATION.md) — Système de validation et retry
- [TEMPLATES.md](TEMPLATES.md) — Architecture des templates Jinja2
- [CODING_STANDARDS.md](CODING_STANDARDS.md) — Standards de code
