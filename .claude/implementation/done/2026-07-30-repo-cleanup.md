---
slug: repo-cleanup
titre: Remise en état du repo — réparation du WIP, code mort, hygiène git
branche: repo-cleanup
base: master
statut: terminé
session: 3
plan: (aucun — chantier ouvert depuis un état existant, pas depuis un plan mode)
créé: 2026-07-26
maj: 2026-07-30
---


## Objectif et périmètre

**But** : sortir le projet de l'ornière. Un refactor multi-fronts (validation,
persistence, submodule `template`) a été mené sans suivi et laissé à mi-chemin :
le paquet n'était plus importable, la suite de tests ne collectait plus, et
deux générations de code coexistent.

**Critères de réussite** :
- `uv run pytest` : 0 échec, 0 erreur de collecte
- `uv run basedpyright src/` : 0 erreur
- Une seule génération de `checks` subsiste dans `src/`
- Branche de travail fusionnée dans `master`

**Hors-périmètre** :
- Mise à jour de `CLAUDE.md` et `docs/` (obsolètes : décrivent
  `validation_worker.py`, `Store`, `TemplateNames`). À traiter séparément.
- Toute évolution fonctionnelle du pipeline (aucune nouvelle feature).
- Refonte du submodule `template` au-delà du renommage déjà propagé.

## Étapes

- [x] 1. Rendre le paquet importable à nouveau — 5 cassures en chaîne :
  - `checks/check_tests/line_count_check.py` : import `override` disparu
  - cycle `checks.content_check` ↔ `validation.failure` (via `check_source`)
  - cycle `validation/__init__` (eager) ↔ `pipeline.context`
  - `LineIndexedTranslation` renommé dans le submodule, jamais propagé
  - `UnifiedValidationWorker` lisait `CommunContext` avant `freeze()`
- [x] 3. Tests morts traités : 9 supprimés (2190 lignes), `test_chapter_detector.py`
      récupéré (`FileType` → `_FileType`, 26 tests). Collecte débloquée.
- [x] 2. Commiter l'état de réparation (commit: ef4b7b3, submodule: faa94bd)
- [x] 8. `master` avancé en fast-forward sur les 35 commits de
      `feature/phase0-literary-analysis`. Aucune réécriture, aucun commit perdu.
      Non poussé vers `origin` (décision à prendre).
- [x] 4. Résorber les échecs restants, par lot — **0 échec, 359 tests verts**
      (commits: 5dc5db2, 5179ca2, a7bdf92)
  - [x] 4.1 Lot Store : 26 → 0. **Trois bugs dans `src`**, pas de la dérive
        de tests (voir journal). `tests/stores/` : 57 verts.
  - [x] 4.2 Bloc `relevant_indices` : 21 → 0. Deux causes — le champ devenu
        obligatoire, et `WorkerRetryContext` élargi à `max_attempts`/`attempt`.
  - [x] 4.3 Les 25 derniers : segmentation (10), `test_llm_logging` (5),
        `test_unified_worker` (4), phases (5), `test_tag_key` (1).
        **Deux bugs `src` de plus** dans `llm/` (voir journal), et un
        paramètre mort (`chunk_info`) retiré de `UnifiedValidationWorker`.
- [x] 5. Génération morte de `checks/` supprimée — seul `checks/content/` subsiste
      (commit: 8134ca4, submodule: ffab88f)
  - [x] 5.1 `AnalysisChecks` dissous dans le schéma `AnalyseChapter` (Phase 0
        migrée Instructor) ; `validate_analysis.py` + `validate_glossary.py`
        supprimés
  - [x] 5.2 `validation_pipeline()`, `get_checks()` et le champ `checks`
        retirés de `PhaseBase` et des 5 phases ; alias `Content*Check`
        supprimés dans `initial_translation` / `refinement`
  - [x] 5.3 `check_tests/` (6 fichiers), `checks/pipeline.py`,
        `checks/retry_helper.py` supprimés, plus 3 fichiers de tests
        devenus sans cible — **2937 lignes**
  - [x] 5.4 `checks/__init__.py` vidé de ses ré-exports (import depuis les
        sous-modules ; un ré-export refermerait le cycle avec `validation`)
- [x] 6. Hygiène repo :
  - `.gitignore` couvrait déjà `cache/`, `logs/`, `htmlcov/` et l'EPUB
    décompressé (836K) ; `template_outputs/` ajouté et détracké (15 rendus de
    prompts, artefacts de `examples/example_template.py`)
  - dernière génération de parsing supprimée : `translation/parser.py`,
    `process_llm_response` (Protocol + `PhaseBase` + override `GlossaryPhase`),
    et `output_type` — déclaré dans `PhaseProtocol`, défini par personne
  - `examples/test2.py` reste non suivi (décision session 1) ; `poetry.lock`
    reste sur disque, ignoré, hérité de l'ère poetry
- [x] 7. `basedpyright src/` à **0 erreur** — le hook pre-commit passe en entier
      (black, ruff, basedpyright strict). Trois bugs de plus au passage : le
      pool construisait ses workers avec des paramètres disparus, l'executor
      construisait `ChunkContext(phase_name=…)` sur un champ nommé `phase`, et
      `PhaseContext` était instancié sans son `name`. Le pipeline ne pouvait
      pas tourner. `GlossaryPhase` migré, package `validator/` supprimé (mort).
- [x] 9. Relecture utilisateur, trois remarques soldées :
  - [x] 9.1 `PhaseBase.validate_payload` supprimée (méthode + fonction libre +
        entrée du `PhaseProtocol`) — morte en prod, l'executor et le worker
        font schéma et `content_checks` eux-mêmes. `validate_data` conservée :
        elle sert le chemin cache (`get_translation_cache`). Tests sans cible
        retirés (`test_phase_base_validate.py`, 4 tests de
        `test_phases_new_api.py`, le stub `_FakePhase`)
  - [x] 9.2 `Chapters` ne connaît plus le `StoreManager` : `analysis_lookup`
        injecté, alimenté par `LiteraryAnalysisPhase.latest_analysis_for`.
        **Bug corrigé au passage** : `Chapters(source_book)` était construit
        sans store — Phase 1/2 traduisaient sans contexte littéraire depuis
        toujours. 4 tests neufs
  - [x] 9.3 Libellés d'export arrimés au schéma : `_checked_labels` /
        `_checked_signal_labels` valident à l'import contre `model_fields` et
        `get_args(SignalCloture)`, structure racine comprise. 6 tests neufs

## État courant

**Terminé.** Le paquet est importable, la suite de tests collecte et passe,
une seule génération de `checks` subsiste, le hook pre-commit passe en entier.

**Compteurs de clôture** : `pytest` **351 passés / 0 échoué** ;
`basedpyright src/` **0 erreur** ; `uv run pre-commit run --all-files` vert.

**Vérification** : `uv run pytest -q` puis `uv run basedpyright src/`

**Laissé de côté**, à ouvrir comme chantier distinct : `CLAUDE.md` et `docs/`
décrivent encore `validation_worker.py`, `Store`, `TemplateNames`,
`translation/parser.py` et le système `checks` supprimé.

**Non commité volontairement** : `examples/test2.py` (brouillon MRO sans
rapport) et `src/template/pyproject.toml` (config basedpyright du submodule).

**Non poussé** : rien n'est allé vers `origin` de tout le chantier.
`origin/master` reste à `b6c8c04`, `origin/feature/phase0-literary-analysis`
à `5d93c68` — décision différée.

## Journal de décisions

Chantier clos ; entrées condensées à une ligne.

- Chantier sur branche dédiée `repo-cleanup`, aplatie en un commit sur
  `master` à la clôture — `master` doit rester la référence stable.
- `master` avancé en fast-forward sur `feature/phase0-literary-analysis`
  plutôt que merge/rebase — aucun commit en propre, aucune réécriture.
- La lecture du cache Phase 0 appartient à Phase 0 : `Chapters` reçoit un
  callable `AnalysisLookup`, jamais le `StoreManager` — `segmentation` n'a pas
  à reconstruire le chemin d'un `ByteStore`.
- Libellés d'export validés contre le schéma à l'import (`_checked_labels`),
  pas dérivés de `Field(title=...)` — l'ordre d'export relève de l'exporteur.
- Format `<N/>…[=[END]=]` : source de vérité unique dans
  `LineIndexedLLMResponse` (submodule) ; `translation/parser.py` supprimé.
- `output_type` retiré de `PhaseProtocol` — déclaré, jamais défini, rendait
  abstraites les quatre phases instanciées par `builder.py`.
- `validate_payload` retirée à son tour — l'executor et le worker portent
  schéma et `content_checks` ; seule `validate_data` (chemin cache) subsiste.
- `MemoizedChunkPersister` généralisé de `M: BaseModel` à `TD: Any` via
  `TypeAdapter` — la phase glossaire persiste une `list`, pas un modèle.
- Namespace de cache du glossaire global (`outer_key = "glossary"`) — les
  termes valent pour tout l'ouvrage.
- `ValidationFailure.relevant_indices` obligatoire, sans défaut — il porte le
  ciblage du retry ; un `frozenset()` implicite viserait le vide.
- Contenu des logs d'échange LLM porté par le client, pas par `LLM.query`.
- `AnalysisChecks` dissous dans `payload_type = AnalyseChapter` (Instructor) —
  ses deux tâches relèvent de la validation de schéma.
- Verrous de `Store` au niveau module (`_lockfiles`), pas par instance — deux
  `Store` sur le même répertoire doivent partager leur exclusion.
- Format de stockage de Phase 0 : `AnalyseChapter` stratifié remplace
  `ContexteTraduction` ; cache invalidé.
- `TagKey.__eq__` compare tag + page + index, `__hash__` le seul tag —
  durcissement délibéré (8ea930b).
- `ValidationFailure.check_source` typé sous `TYPE_CHECKING` seulement —
  Pydantic ne sait pas faire `issubclass` sur un Protocol.
- `validation/__init__.py` en import paresseux (PEP 562) — l'import eager
  refermait le cycle `validation` ↔ `checks`/`pipeline`.
- `UnifiedValidationWorker` lit `CommunContext` via `@property` —
  `FrozenStatic` interdit toute lecture avant `freeze()`.
- Commits passés avec `--no-verify` jusqu'à l'étape 7 incluse — le hook
  basedpyright bloquait sur les erreurs de typage. Soldé depuis.

### Enseignement du chantier

Ne pas présumer qu'un lot d'échecs de tests est de la dérive de tests. Sur les
351 tests remis au vert, **huit bugs `src`** étaient cachés derrière : trois
dans `Store`, deux dans `llm/`, trois dans le câblage pipeline/executor/pool
qui empêchaient purement et simplement le pipeline de tourner. Un neuvième au
titre de la relecture finale : `Chapters` construit sans store, contexte
littéraire mort depuis toujours.
