# Réalignement de la documentation sur le code

## Contexte

Le chantier `repo-cleanup` (clos le 2026-07-30, commit `303ae36`, suivi archivé dans
`.claude/implementation/done/2026-07-30-repo-cleanup.md`) a retiré plusieurs pans entiers du
code — la génération `checks` complète, `translation/parser.py`, les packages `analysis/`,
`transition/` et `validator/` — en plaçant explicitement la documentation hors-périmètre.

Résultat : `CLAUDE.md`, `README.md` et `docs/` décrivent une architecture qui n'existe plus.
Un développeur qui suit la doc aujourd'hui cherche des fichiers absents et implémente contre
des interfaces disparues. Le but est de faire de la doc un reflet vérifié du code, et de
balayer les restes que `repo-cleanup` a laissés derrière lui.

**Baseline vérifiée** : `uv run pytest` → 351 passés ; `uv run basedpyright src/` → 0 erreur.

## Écart constaté (vérifié dans `src/`)

Au-delà des renommages, plusieurs mécanismes ont changé de nature :

| La doc décrit | La réalité du code |
|---|---|
| `ValidationPipeline` + `checks/pipeline.py` + `checks/check_tests/` | `UnifiedValidationWorker` (`validation/unified_worker.py`) + `content_checks` déclarés par chaque phase, protocole `ContentCheck` (`checks/content_check.py`), impls dans `checks/content/` |
| retry via `checks/retry_helper.py` | `RetryStrategy` (`validation/retry_strategy.py`) + `retry_registry.py` (mapping erreur → template) + `worker_retry.py` |
| `Store` seul dépositaire du cache | `Store` subsiste (per-phase, via `StoreManager`), mais l'I/O passe par `PhaseStorage` = `ChunkPersister` + `ByteStore` (`FileByteStore`), avec `LineIndexedPersister` et `MemoizedChunkPersister` |
| Phase 0 → `ContexteTraduction` validé par `AnalysisValidator` (`analysis/`) | Phase 0 → `AnalyseChapter` stratifié via Instructor (`template/phase/analyze_chapter_layered_models.py`) ; `analysis/` n'existe plus, l'export vit dans `exporter/` |
| « Transition GlossaryValidation » (`transition/`) | `GlossaryPhase` — une **phase** à part entière (`pipeline/phases/glossary.py`), `transition/` n'existe plus |
| format `<N/>…[=[END]=]` parsé par `translation/parser.py` | source de vérité unique : `LineIndexedLLMResponse` (`template/phase/translation_models.py`) |
| templates plats (`translate_base.jinja`, `analyze_chapter_simplified.jinja`) | paires `*_system.jinja` / `*_user.jinja` réparties en `common/`, `phase/`, `retry/` ; enums `PhaseTemplate` / `RetryTemplate` |
| entry point `src/ebook_translator/__main__.py` | **le fichier n'existe pas** |
| *(absent de la doc)* | `PipelineBuilder` / `LLMBuilder` / `PhasesBuilder` (`pipeline/builder.py`) — l'API publique de configuration |

## Décisions arrêtées avec l'utilisateur

1. `docs/REFACTOR_PHASEBASE.md` → **archivé** vers `.claude/implementation/done/`, sorti de
   `docs/` et du Documentation Map. C'est un doc de chantier, pas une référence.
2. `docs/CHANGELOG.md` (1679 lignes, 64 Ko, dernière entrée 0.11.0) → **archivé tel quel** sous
   `docs/CHANGELOG_ARCHIVE.md`, et **repartir d'un `CHANGELOG.md` propre** dont la première
   entrée est 0.12.0. L'historique reste consultable sans polluer le document courant de
   symboles disparus.
3. Bug `LLMBuilder.build()` → **corrigé, avec test**. C'est une réparation, pas une évolution.

## Étapes

### 1. Réparer `LLMBuilder` et `examples/example_phase0_analysis.py`

`LLMBuilder.build()` lève `TypeError: LLM.__init__() got an unexpected keyword argument
'model_name'` : il passe `model_name` / `reasoning_name` / `url` / `temperature` alors que
`LLM.__init__` (`llm/llm.py:31`) attend un `client: ClientProviderProtocol`. Le
`**_skip_none(...)` typé `dict[str, Any]` masque l'erreur à basedpyright. L'API publique
annoncée par le docstring du module est donc inutilisable.

- `pipeline/builder.py` : construire le client via `llm/clients/deepseek.py` à partir de
  `model`/`reasoning`/`url`/`temperature`, puis passer `client=` à `LLM`, en ne conservant en
  kwargs directs que ce que `LLM.__init__` accepte réellement (`api_key`, `prompt_dir`,
  `max_retries`, `retry_delay`, `glossary_max_terms`). Supprimer l'indirection `_skip_none`
  sur le chemin `LLM` pour que basedpyright voie l'appel.
- `examples/example_phase0_analysis.py` : réécrire l'instanciation `LLM` sur la même API.
- **Tests** : `tests/pipeline/test_builder.py` — `LLMBuilder().model().reasoning().url().build()`
  retourne un `LLM`, les `ValueError` des champs requis, et un `PipelineBuilder` complet
  construit ses phases. Aucun appel réseau.
- Vérification : `uv run basedpyright src/ examples/` → 0 erreur.

### 2. Réécrire `docs/ARCHITECTURE.md`

Document pivot (279 lignes, 20 refs mortes). Réécrire section par section en vérifiant chaque
affirmation dans `src/` :

- flux : insérer `GlossaryPhase` comme phase, retirer la « Transition »
- `PhaseBase` : remplacer `checks` par `content_checks`, ajouter `payload_type` / `data_type` /
  `chunk_type` / `persister`, et `get_llm_config()`
- section « Validation et sauvegarde » : `UnifiedValidationWorker`, `ContentCheck`,
  `RetryStrategy` + `retry_registry`, `worker_retry`
- nouvelle section « Persistance » : `StoreManager` → `Store`, `PhaseStorage`,
  `ChunkPersister` (`LineIndexedPersister`, `MemoizedChunkPersister`), `ByteStore` /
  `FileByteStore`
- supprimer la section « Parser » ; renvoyer vers `LineIndexedLLMResponse`
- nouvelle section « API publique » : `PipelineBuilder` / `LLMBuilder` / `PhasesBuilder`
- corriger le lien cassé `segmentation/chunk.py` (pointe vers `../src/ebook_translator/chunk.py`)

### 3. Réécrire `docs/VALIDATION.md` et `docs/TEMPLATES.md`

- `VALIDATION.md` : remplacer `ValidationPipeline` par le cycle réel du worker unifié
  (schéma Pydantic/Instructor d'abord, puis `content_checks`, puis retry ciblé via
  `relevant_indices`) ; table des checks pointant sur `checks/content/` ; interface
  `ContentCheck` (`error_type`, `retry_strategy`, `max_attempts`, `run()`) ; noms de templates
  retry réels (paires `_system`/`_user`) — retirer `retry_correct_fragments_flexible` qui
  n'existe pas.
- `TEMPLATES.md` : arborescence réelle `common/` / `phase/` / `retry/`, convention de paires
  `*_system.jinja` + `*_user.jinja`, enums `Template` / `PhaseTemplate` / `RetryTemplate`,
  méthodes `render_*()` effectivement présentes (dont `render_analyze_chapter_layered`,
  `render_glossary`).

### 4. Réécrire `docs/LITERARY_ANALYSIS.md`

Remplacer le schéma `ContexteTraduction` par `AnalyseChapter` stratifié (lu depuis
`template/phase/analyze_chapter_layered_models.py`, pas recopié de mémoire). Supprimer
`AnalysisValidator` (Instructor valide), rediriger `AnalysisExporter` vers
`exporter/analysis_exporter.py`. Documenter le chemin de lecture réel du cache :
`LiteraryAnalysisPhase.latest_analysis_for` → `AnalysisLookup` injecté dans `Chapters`.

### 5. Mettre à jour `CLAUDE.md` et `README.md`

- `CLAUDE.md` : corriger l'entry point (`__main__.py` absent → `examples/example_pipeline.py`
  ou `PipelineBuilder`), la table des modules (`validation/`, `checks/`, retirer `analysis/` et
  `transition/`, ajouter `persistence/`, `exporter/`), les sections Data Formats / Phase 0 /
  Validation / Templates, et le Documentation Map (retirer `REFACTOR_PHASEBASE.md`).
- `README.md` : liste des checks et arborescence `src/` (lignes ~155-183).

### 6. `docs/CODING_STANDARDS.md`

Les 12 refs mortes sont dans des **exemples de code** (`LineCountCheck`, `Check`,
`ValidationPipeline`, arborescence `check_tests/`). Remplacer par des exemples tirés du code
vivant (`ContentCheck` / `checks/content/`) — la substance des standards ne change pas.

### 7. Archiver `docs/REFACTOR_PHASEBASE.md`

`git mv docs/REFACTOR_PHASEBASE.md .claude/implementation/done/2026-07-30-refactor-phasebase.md`,
avec un entête court signalant qu'il s'agit d'une archive de chantier atteint. Retirer l'entrée
du Documentation Map (`CLAUDE.md`) et tout lien entrant depuis `docs/`.

### 8. Archiver le changelog et repartir propre

1. `git mv docs/CHANGELOG.md docs/CHANGELOG_ARCHIVE.md` — contenu **inchangé**, hormis un
   entête de deux lignes précisant qu'il couvre 0.2.0 → 0.11.0 (2025-10-19 → 2025-11-15) et
   que les symboles qui y sont cités peuvent ne plus exister.
2. Nouveau `docs/CHANGELOG.md` : entête, lien vers `CHANGELOG_ARCHIVE.md` et vers
   `ROADMAP.md`, un tableau récapitulatif vide hormis 0.12.0, puis l'entrée 0.12.0 seule —
   au format des entrées existantes, repris de l'archive.
3. Contenu de 0.12.0 : pivot TypedDict / `ByteStore` / `PhaseStorage` / `ChunkPersister`,
   Phase 0 migrée Instructor (`AnalyseChapter` remplace `ContexteTraduction`, cache invalidé),
   `UnifiedValidationWorker` + `content_checks` en remplacement de `ValidationPipeline`,
   `GlossaryPhase` (l'ancienne transition devient une phase), source de vérité unique
   `LineIndexedLLMResponse`, réorganisation des templates en paires `_system`/`_user`, et le
   solde `repo-cleanup` (9 bugs `src` corrigés, ~5000 lignes retirées, 351 tests verts).
   Sourcer les faits depuis `.claude/implementation/done/2026-07-30-repo-cleanup.md` et
   l'historique git, pas de mémoire.
4. Mettre à jour les liens entrants : Documentation Map de `CLAUDE.md` (ajouter l'archive),
   et la note liminaire de `ROADMAP.md` si elle pointe le changelog.

Ne rien réécrire des entrées ≤ 0.11.0 : elles ne bougent que de fichier.

### 9. Balayer les restes

- `src/ebook_translator/validator/` : 0 fichier suivi par git, ne subsiste qu'un
  `__pycache__` sur disque → supprimer le répertoire.
- `tests/transition/` : `__init__.py` + `conftest.py`, aucun test, src disparu → supprimer.
- `tests/checks/check_tests/` : `__init__.py` + `conftest.py`, aucun test → supprimer.
- `tests/analysis/` : ne contient plus que `test_analysis_exporter.py` — vérifier qu'il cible
  bien `exporter/analysis_exporter.py` et, si oui, renommer le dossier en `tests/exporter/`.
- `poetry.lock` (167 Ko, ignoré via `.gitignore:30`, hérité de l'ère poetry) → supprimer du
  disque, et retirer la ligne du `.gitignore` devenue sans objet.
- `examples/` : passer les 7 fichiers au type-check ; `example_template.py` produisait
  `template_outputs/` (détracké au chantier précédent) — le conserver s'il tourne, sinon le
  réparer. Décider de `test.py` (script ad-hoc de 1,2 Ko sans rapport avec les autres exemples).
- Docstrings `src/` citant du code mort : `pipeline/phases/glossary.py:5` (`GlossaryValidator`),
  `persistence/memoized_chunk_persister.py:11` (`ContexteTraduction`).
- Recherche de symboles `src/` sans appelant, dans la lignée de `repo-cleanup`.

### 10. Vérification finale

`uv run pytest` (≥ 351 passés, 0 échec), `uv run basedpyright src/ examples/` (0 erreur),
`uv run pre-commit run --all-files` (vert), puis un grep de contrôle des symboles morts sur
`CLAUDE.md`, `README.md` et `docs/` hors `CHANGELOG.md`.

## Hors-périmètre

- Toute évolution fonctionnelle du pipeline (aucune feature nouvelle ; l'étape 1 est une
  réparation d'API cassée, pas une évolution).
- Toute refonte du submodule `template` — sa doc est lue, pas réécrite.
- Réécriture des entrées de changelog ≤ 0.11.0 : elles sont déplacées vers
  `docs/CHANGELOG_ARCHIVE.md`, pas corrigées.
- Décision sur le push vers `origin` (`origin/master` est à `b6c8c04`, très en arrière du
  `master` local) — à traiter séparément.
- `docs/ROADMAP.md` et `docs/SETUP.md` : 0 ref morte, non touchés.

## Critères de réussite

- Plus aucune référence à un symbole inexistant dans `CLAUDE.md`, `README.md` et `docs/`
  (hors `docs/CHANGELOG_ARCHIVE.md`, historique assumé).
- `uv run pytest` : 0 échec. `uv run basedpyright src/` : 0 erreur.
  `uv run pre-commit run --all-files` : vert.
- `LLMBuilder().model().reasoning().url().build()` retourne un `LLM`, couvert par un test.

## Vérification

```bash
uv run pytest -q
uv run basedpyright src/ examples/
uv run pre-commit run --all-files
# contrôle des symboles morts (ne doit rien retourner hors l'archive)
grep -rnE "validation_worker\.py|TemplateNames|translation/parser|process_llm_response|check_tests|ValidationPipeline|checks/pipeline|retry_helper|ContexteTraduction|GlossaryValidator|output_type|analysis/validator" \
  CLAUDE.md README.md docs/ --exclude=CHANGELOG_ARCHIVE.md
```

## Conduite du chantier

Suivi via `implementation-tracker` : fichier `.claude/implementation/docs-realignment.md`,
branche d'implémentation `docs-realignment` créée depuis `master` (cible de l'aplatissement
final). Commit proposé à chaque étape cochée.
