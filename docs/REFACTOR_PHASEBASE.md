# Refactor : PhaseBase autour de ConvertibleModel

## Objectif

Faire que `PhaseBase` ne manipule **que** des `ConvertibleModel` typés (plus de
`dict[int, str]` anonyme qui voyage à travers le pipeline). Unifier les voies
texte (Phase 1/2) et JSON (Phase 0, Glossaire) derrière une seule abstraction
`M: ConvertibleModel`.

## Principes directeurs

1. **Schéma vs contenu** : le modèle Pydantic valide le format et la structure ;
   les checks externes valident la fidélité à la source.
2. **Erreurs typées de bout en bout** : un seul type `ValidationFailure[CtxT]`
   pour toutes les erreurs, peu importe leur origine (Pydantic ou check externe).
3. **Source de vérité unique par artefact** : format de sortie LLM dans le modèle,
   schéma JSON dans le modèle, params template dans `template_params.py`,
   mapping erreur → retry dans un registre unique.
4. **Stateless retry** : chaque tentative est un nouvel appel API avec ses propres
   prompts (system + user), pas une conversation multi-turn.
5. **Migration additive** : étapes 1-4 ajoutent du code sans casser l'existant ;
   étapes 5-9 migrent en série avec basedpyright à 0 et tests verts à chaque commit.

## Architecture cible

```
┌────────────────────────────────────────────────────────────────────┐
│ PhaseBase[M: ConvertibleModel[Any]]                                │
│   payload_type: ClassVar[type[M]]                                  │
│   content_checks: ClassVar[tuple[ContentCheck[M, Any], ...]]       │
│   retry_strategy: ClassVar[RetryStrategy]                          │
│   max_attempts: ClassVar[int]                                      │
│                                                                    │
│   render_prompt(chunk, ctx) -> (system, user)                      │
│   get_llm_config(chunk, ctx) -> LLMConfig | InstructorConfig[M]    │
│   validate(raw, source) -> M | list[Failure]                       │
│   save_item_builder(chunk, m: M) -> SaveItem[M]                    │
└────────────────────────────────────────────────────────────────────┘
                              │
            ┌─────────────────┴─────────────────┐
            ▼                                   ▼
┌──────────────────────────┐       ┌────────────────────────────┐
│ Schéma (Pydantic)        │       │ Checks externes            │
│ - parsing (validator     │       │ - cross-source             │
│   mode="before")         │       │ - retournent               │
│ - structure              │       │   ValidationFailure[Diag]  │
│ - PydanticCustomError    │       │ - aucun ne tourne si       │
│   typés                  │       │   schéma KO                │
└──────────────────────────┘       └────────────────────────────┘
            │                                   │
            └────────────┬──────────────────────┘
                         ▼
            ┌────────────────────────────┐
            │ ValidationFailure[CtxT]    │
            │ + RETRY_REGISTRY           │
            │ → render retry prompt      │
            │ → re-call LLM              │
            │ → combine (replace|merge)  │
            └────────────────────────────┘
```

## Contrats de types

### `ValidationFailure[CtxT]`

```python
class ValidationFailure[CtxT: Mapping[str, Any]](BaseModel):
    error_type: str                      # clé du registre
    msg: str                             # message debug/log
    ctx: CtxT                            # diagnostic typé
    loc: tuple[str | int, ...] = ()
```

### Diagnostics (`validation/diagnostics.py`)

Une `TypedDict` par `error_type` représentant **uniquement** ce que le check
produit (pas de fuite environnementale type `target_language` ou `source_text`).

```python
class OutputFormatDiagnostic(TypedDict):    detail: str
class LinesMissingDiagnostic(TypedDict):    missing_indices: list[int]
class FragmentDiagnostic(TypedDict):        line: int; expected_pairs: int; actual_pairs: int
class PunctuationDiagnostic(TypedDict):     expected_pairs: int; actual_pairs: int
class SentenceDiagnostic(TypedDict):        invalid_indices: list[int]
class AnalysisInvalidJsonDiagnostic(TypedDict):    json_error_message: str
class AnalysisMissingSectionsDiagnostic(TypedDict): missing_sections: list[str]

type Failure = (
    ValidationFailure[OutputFormatDiagnostic]
    | ValidationFailure[LinesMissingDiagnostic]
    | ValidationFailure[FragmentDiagnostic]
    | ValidationFailure[PunctuationDiagnostic]
    | ValidationFailure[SentenceDiagnostic]
    | ValidationFailure[AnalysisInvalidJsonDiagnostic]
    | ValidationFailure[AnalysisMissingSectionsDiagnostic]
)
```

### Registre retry (`llm/retry_registry.py`)

```python
@dataclass(frozen=True)
class RetryEntry[D: Mapping[str, Any], P: Mapping[str, Any]]:
    template: str                        # nom du template Jinja
    params_type: type[P]                 # Retry*Params de template_params.py
    build: Callable[                     # diagnostic + env -> params
        [ValidationFailure[D], ChunkSource, PhaseConfig], P
    ]
    mode: Literal["replace", "merge"]    # comment la sortie LLM est combinée

RETRY_REGISTRY: dict[str, RetryEntry[Any, Any]] = {
    "output_format_invalid":       RetryEntry(..., mode="replace"),
    "missing_end_marker":          RetryEntry(..., mode="replace"),
    "duplicate_indices":           RetryEntry(..., mode="replace"),
    "lines_missing":               RetryEntry(..., mode="merge"),
    "fragment_count_mismatch":     RetryEntry(..., mode="replace"),
    "punctuation_mismatch":        RetryEntry(..., mode="replace"),
    "sentence_invalid":            RetryEntry(..., mode="merge"),
    "analysis_invalid_json":       RetryEntry(..., mode="replace"),
    "analysis_missing_sections":   RetryEntry(..., mode="replace"),
}
```

**Règle invariante** : tout `error_type` émis (par Pydantic ou check externe)
DOIT être présent dans `RETRY_REGISTRY`. Test d'intégration garantit la couverture.

### Stratégie retry (`validation/retry_strategy.py`)

```python
class RetryStrategy(StrEnum):
    NORMAL_ONLY = "normal_only"
    PROGRESSIVE_REASONING = "progressive"   # T0 normal, T1+ reasoning
    REASONING_ONLY = "reasoning_only"
```

### `ContentCheck` Protocol (`checks/content_check.py`)

```python
class ContentCheck[M: ConvertibleModel[Any], CtxT: Mapping[str, Any]](Protocol):
    error_type: ClassVar[str]
    def run(self, payload: M, source: ChunkSource) -> ValidationFailure[CtxT] | None: ...
```

### `ValidationItem[M]`

```python
@dataclass
class ValidationItem[M: ConvertibleModel[Any]]:
    chunk: Chunk
    context: PipelineContext
    phase: PhaseBase[M]
    initial_output: str | M
    last_partial_m: M | None = None
    attempt_history: list[Attempt] = field(default_factory=list)
```

### Cycle de validation (worker)

```
T0:  initial_output -> validate -> M | failures
                                       │
                                       ▼
                                  failure[0]
                                  entry = REGISTRY[failure.error_type]
                                  params = entry.build(failure, chunk, config)
                                  prompt = render(entry.template, params)
                                  llm = strategy_for_attempt(phase.retry_strategy, attempt)
                                  raw' = llm.query(prompt)
                                  combine(last_partial_m, raw', entry.mode) -> raw_or_m
                                       │
                                       ▼
T1:  validate(raw_or_m) -> ...
```

`combine` :
- `mode == "replace"` : `raw_or_m = raw'`
- `mode == "merge"`   : `raw_or_m = last_partial_m.merge(payload_type.model_validate(raw'))`

`last_partial_m` est mis à jour après chaque échec où `model_validate(raw)`
réussit structurellement (cas A : schéma OK, contenu KO). En cas B (schéma KO),
`last_partial_m` reste `None` et le mode `merge` ne peut pas s'appliquer
— cohérent avec la règle "schéma KO => mode = replace".

## Étapes d'implémentation

### Étape 1 : Fondations (additif, sans dépendance)

**Fichiers créés** :
- `src/ebook_translator/validation/failure.py`
- `src/ebook_translator/validation/diagnostics.py`
- `src/ebook_translator/validation/retry_strategy.py`
- `src/ebook_translator/llm/retry_registry.py`

**Tests** :
- `tests/validation/test_failure.py` : construction et conversion `from_pydantic_error`
- `tests/llm/test_retry_registry.py` :
  - Chaque clé pointe vers un template Jinja existant sur disque
  - Chaque `params_type` est bien une `TypedDict` de `template_params.py`
  - Couverture : tout `error_type` émis dans le code apparaît dans le registre

**Done si** : basedpyright 0 erreur, tests verts, aucun import depuis le pipeline existant.

---

### Étape 2 : `LineIndexedTranslation`

**Fichiers** :
- `src/template/phase/translation_models.py` (nouveau)

**Contenu** :
- Class `LineIndexedTranslation(ConvertibleModel[...])`
- `@model_validator(mode="before")` : parse `<N/>...[=[END]=]` (regex migré depuis `parser.py`)
- `@model_validator(mode="after")` : vérifie marqueur de fin, indices uniques
- Helpers : `merge`, `line_indices`, `fragments_at`, `format_spec` (constante)
- `PydanticCustomError` typés : `output_format_invalid`, `missing_end_marker`, `duplicate_indices`

**Tests** :
- `tests/template/test_translation_models.py` :
  - Parse réussi sur sortie LLM valide
  - Chaque erreur structurelle remonte avec le bon `error_type`
  - `merge` : union, écrasement sur indices communs, idempotence

**Done si** : `LineIndexedTranslation` testé en isolation, parser legacy non encore supprimé.

---

### Étape 3 : `ContentCheck` Protocol + check pilote

**Fichiers** :
- `src/ebook_translator/checks/content_check.py` (Protocol)
- `src/ebook_translator/checks/content/line_count_check.py` (pilote)

**Tests** :
- `tests/checks/test_line_count_check.py` :
  - OK si toutes lignes présentes
  - `ValidationFailure[LinesMissingDiagnostic]` avec indices manquants

**Done si** : un seul check migré, ancien `LineCountCheck` toujours en place.

---

### Étape 4 : Migrer les checks restants

Itérer pour `FragmentCountCheck`, `PunctuationCheck`, `SentenceCheck`. Pour
chacun :
- Implémentation côté nouveau Protocol
- Diagnostic typé
- Tests unitaires

**Done si** : 4 checks contenu migrés, anciens encore en place mais marqués
deprecated.

---

### Étape 5 : `PhaseBase[M]` générique

**Modifications** :
- `src/ebook_translator/pipeline/base.py` :
  - `PhaseBase` devient `PhaseBase[M: ConvertibleModel[Any]]`
  - Ajout : `payload_type`, `content_checks`, `retry_strategy`, `max_attempts`
  - Ajout : `validate(raw, source) -> M | list[Failure]`
  - Suppression progressive : `process_llm_response`, `output_type`
- Helper : `from_pydantic_error(e: ValidationError) -> list[Failure]`

**Tests** :
- `tests/pipeline/test_phase_base_validate.py` :
  - Schéma OK + contenu OK → renvoie `M`
  - Schéma KO → renvoie failures Pydantic typées
  - Schéma OK + contenu KO → renvoie failures content
  - Schéma KO empêche les checks contenu de tourner

**Done si** : signature générique en place, mais aucune phase ne l'utilise encore.

---

### Étape 6 : Migrer Phases 1 et 2

**Modifications** :
- `pipeline/phases/initial_translation.py` :
  - `PhaseBase[LineIndexedTranslation]`
  - `payload_type = LineIndexedTranslation`
  - `content_checks = (LineCountCheck(), FragmentCountCheck(), PunctuationCheck(), SentenceCheck())`
  - `retry_strategy = RetryStrategy.PROGRESSIVE_REASONING`
- Idem pour `refinement.py`

**Done si** : Phase 1 et 2 utilisent la nouvelle API, ancien code parallèle peut être désactivé via flag pour rollback.

---

### Étape 7 : `ValidationItem[M]`, `SaveItem[M]`, `Store[M]`, executor unifié

**Le gros morceau.** Touche pipeline parallèle.

**Modifications** :
- `pipeline/executor.py` : branche unique. Plus d'`isinstance(JsonRequestConfig)`.
- `validation/validation_queue.py`, `validation_worker.py`, `save_worker.py` :
  génériques `[M]`.
- `stores/store.py` : `Store[M]`. Sérialisation via `M.serialized_build()`,
  désérialisation via `M.model_validate_json(...)`.
- Worker boucle : `validate -> registry -> render -> llm -> combine -> validate`.

**Tests** :
- E2E sur EPUB de référence (avant/après cache identique)
- Test de rejet après `MAX_ATTEMPTS`
- Test mode `merge` sur `lines_missing`
- Test mode `replace` sur `fragment_count_mismatch`

**Done si** : pipeline complet sur Phases 1/2 fonctionne, basedpyright 0,
performance équivalente.

---

### Étape 8 : Migrer Phase 0 et Glossaire

Déjà Pydantic via Instructor. Suppression du `.serialized_build() -> str -> re-parse`.

**Modifications** :
- `pipeline/phases/literary_analysis.py` :
  - `PhaseBase[AnalyseChapter]`
  - `payload_type = AnalyseChapter`
  - `content_checks = ()`
  - `retry_strategy = RetryStrategy.NORMAL_ONLY`
- `pipeline/phases/glossary.py` : idem avec `LLMGlossaryModel`.
- Executor passe `M` directement depuis Instructor au worker (pas de
  sérialisation intermédiaire).

**Done si** : phases JSON consomment et produisent `M` natif tout du long.

---

### Étape 9 : Suppression du code mort

À supprimer :
- `src/ebook_translator/translation/parser.py`
- `src/ebook_translator/validator/analysis_validator.py`
- `src/ebook_translator/validator/glossary_validator.py`
- Anciens `Check` text-bound (`checks/check_tests/*` legacy)
- `JsonRequestConfig` si remplacé par `InstructorConfig`
- `process_llm_response` overrides
- `.serialized_build()` aller-retour dans `executor.py`
- Special-case clé-chapitre dans `Store`
- Flag de rollback de l'étape 6

**Done si** : `git grep` ne trouve plus aucune trace, basedpyright 0, tests verts.

---

### Étape 10 : Validation finale

- Run E2E sur EPUB de référence complet (3 chapitres minimum, Phase 0+1+2)
- Comparer cache JSON avant/après → traductions identiques (à variabilité LLM près)
- Comparer logs : nombre de retries, types d'erreurs, taux de rejet
- `uv run pre-commit run --all-files` → 0 erreur
- `uv run pytest --cov=src/ebook_translator` → couverture ≥ 80% sur le code touché
- Mettre à jour `docs/ARCHITECTURE.md` et `docs/VALIDATION.md`

## Suppressions finales (récap)

| Artefact | Remplacé par |
|----------|--------------|
| `translation/parser.py` | `LineIndexedTranslation._parse` (model_validator) |
| `validator/analysis_validator.py` | Pydantic + Instructor sur `AnalyseChapter` |
| `validator/glossary_validator.py` | Pydantic + Instructor sur `LLMGlossaryModel` |
| `process_llm_response` overrides | `model_validate` dans `PhaseBase.validate` |
| `JsonRequestConfig` | `InstructorConfig[M]` |
| Anciens `Check` text-bound | `ContentCheck[M, CtxT]` |
| `.serialized_build()` aller-retour | Passage direct `M` executor → worker → store |
| Special-case clé-chapitre dans Store | `Store[M]` typé par phase |
| `dict[int, str]` voyageant le pipeline | `M: ConvertibleModel` typé partout |

## Risques et mitigations

| Risque | Probabilité | Mitigation |
|--------|-------------|------------|
| Régression sur cache existant après migration parser | Moyenne | Étape 2 isole `LineIndexedTranslation` testée seule ; étape 6 bascule via flag |
| `ValidationItem[M]` casse le multi-threading (typage Generic + queue) | Moyenne | Tests E2E à l'étape 7 ; rollback possible via flag étape 6 |
| Erreurs Pydantic remontent dans un ordre inattendu | Faible | Option 1 (ordre Pydantic natif) au début, registre de priorité explicite ajouté seulement si nécessaire |
| `merge` sur `LineIndexedTranslation` perd des lignes en cas de fusion partielle | Faible | Tests dédiés ; sémantique = nouveau écrase ancien sur indices communs |
| Templates retry attendent des champs absents du `Retry*Params` rempli par `build` | Faible | basedpyright vérifie le retour de `build` contre `params_type` |

## Critères de validation globale

À la fin de l'étape 10 :
1. `uv run basedpyright src/` → 0 erreur
2. `uv run pytest` → tous verts
3. `uv run pre-commit run --all-files` → 0 erreur
4. Aucune référence à `parser.py`, `analysis_validator.py`, `glossary_validator.py` dans le code
5. Aucune occurrence de `dict[int, str]` dans `pipeline/`, `validation/`, `stores/`
6. `PhaseBase` est paramétré `[M]` partout
7. Toute erreur émise (Pydantic ou check externe) a une entrée `RETRY_REGISTRY`
8. Tests E2E sur EPUB de référence : sortie identique au comportement pré-refactor

## Ordre de commit suggéré

Un commit par étape majeure, message conventionnel :

```
feat(validation): add ValidationFailure and diagnostics types
feat(template): add LineIndexedTranslation Pydantic model
feat(checks): add ContentCheck protocol and migrate LineCountCheck
feat(checks): migrate Fragment/Punctuation/Sentence checks
feat(pipeline): make PhaseBase generic over ConvertibleModel
refactor(phases): migrate Phase 1 and 2 to PhaseBase[M]
refactor(pipeline): unify executor/worker/store on generic M
refactor(phases): migrate Phase 0 and Glossary to native M passthrough
chore: remove legacy parser, validators, and dead code paths
docs: update ARCHITECTURE and VALIDATION for new pipeline
```
