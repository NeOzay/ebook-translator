# Système de validation

La validation se fait en **deux temps**, portés par deux composants distincts :

1. **Le schéma** — `phase.payload_type` (modèle Pydantic) valide la forme de la sortie LLM. C'est l'executor qui l'applique, avant toute mise en queue.
2. **Le contenu** — `phase.content_checks` valide la fidélité à la source (lignes présentes, fragments préservés, ponctuation équilibrée…). C'est le worker de validation qui les applique, et qui déclenche les corrections.

Une phase peut n'avoir que le premier : Phase 0 et la phase glossaire déclarent `content_checks = ()`, leur schéma Pydantic suffisant.

## Architecture multi-thread

```
ValidationQueue → N × UnifiedValidationWorker (checks + appels LLM de correction)
                        ↓ (si succès)
                     SaveQueue → 1 × SaveWorker (I/O) → ChunkPersister → ByteStore
```

**Fichiers clés** :
- Pool : [validation/validation_worker_pool.py](../src/ebook_translator/validation/validation_worker_pool.py)
- Worker : [validation/unified_worker.py](../src/ebook_translator/validation/unified_worker.py)
- Helpers de retry : [validation/worker_retry.py](../src/ebook_translator/validation/worker_retry.py)
- Save : [validation/save_worker.py](../src/ebook_translator/validation/save_worker.py)
- Queues et items : [validation/validation_queue.py](../src/ebook_translator/validation/validation_queue.py)

## ValidationWorkerPool

Interface utilisée par `PhaseExecutor` :

- `switch_phase(phase)` : reconfigure les workers pour la phase courante
- `submit(ValidationItem)` : soumet un chunk à valider
- `wait_completion()` : bloque jusqu'à vidage des queues
- `get_statistics()` : `ValidationPoolStats` (validés, rejetés, en attente, total soumis)

Le pool est construit une seule fois par run, avec une `DummyPhase` en attendant le premier `switch_phase()`.

## UnifiedValidationWorker

Un **seul** worker sert toutes les phases : aucune sous-classe par phase. Le routage des corrections passe entièrement par `RETRY_REGISTRY` et par les métadonnées portées par chaque `ContentCheck`.

### Cycle check par check

Les `content_checks` sont parcourus **dans l'ordre de déclaration**. Chaque check épuise son budget de retries sur ses propres échecs avant de passer la main au suivant ; les checks déjà traités ne sont jamais réévalués.

Pour un check donné :

1. `failures = check.run(data, source)`
2. Tant qu'il reste des échecs, prendre le premier et tenter jusqu'à `check.max_attempts` corrections :
   a. `RETRY_REGISTRY[error_type]` → `entry.build(failure, ctx)` → rendu du template → appel LLM → parse du schéma → `merge_data(data, new, entry.mode)`
   b. re-run **du seul check courant** ; si l'instance a disparu (`is_instance_resolved`), passer à l'échec suivant
3. Si l'instance survit au budget, les `relevant_indices` de l'échec sont **retirés** de `data`, l'`error_type` est marqué comme renoncé pour ces indices, et le traitement continue

Un chunk peut donc être sauvegardé **partiel** : on préfère un chunk avec des trous à un chunk rejeté. Le rejet pur ne survient que si le schéma casse lors d'un retry, ou si un `error_type` n'a pas d'entrée dans le registre.

### Sélection du modèle

`_run_one_retry` demande la configuration au client via `get_model_preset_config("high", attempt_index == max_attempts - 2)` : l'avant-dernière tentative passe en mode thinking.

> **Écart connu** — `ContentCheck.retry_strategy` et le helper `lookup_strategy()` ([worker_retry.py](../src/ebook_translator/validation/worker_retry.py)) décrivent une politique par check (`NORMAL_ONLY`, `PROGRESSIVE_REASONING`, `REASONING_ONLY`), mais **le worker ne les consulte pas** : le branchement est marqué « déféré » dans le code. Ces métadonnées sont aujourd'hui déclaratives et couvertes par les tests, sans effet en production.

## SaveWorker

Consomme `SaveQueue` en FIFO et délègue l'écriture au `ChunkPersister` porté par le `SaveItem`. Bénéfices :

- les workers de validation ne bloquent jamais sur les écritures disque
- les callbacks `on_save` s'exécutent après confirmation d'écriture
- ordre déterministe des sauvegardes, ce qui facilite le débogage

## Interface ContentCheck

**Fichier** : [checks/content_check.py](../src/ebook_translator/checks/content_check.py)

```python
class ContentCheck[DT, CtxT](Protocol):
    error_type: ClassVar[ErreursType]      # route vers RETRY_REGISTRY
    retry_strategy: ClassVar[RetryStrategy]
    max_attempts: ClassVar[int]

    def run(self, data: DT, source: ChunkSource) -> list[ValidationFailure[CtxT]]: ...
```

Un check **détecte**, il ne corrige pas : la correction est produite par le registre de retry. `ChunkSource` est l'accès minimal à la source (`line_indices()`, `text_at(index)`), ce qui garde les checks indépendants du type de chunk.

### ValidationFailure

**Fichier** : [validation/failure.py](../src/ebook_translator/validation/failure.py)

Type unique pour toutes les erreurs, quelle que soit leur origine (Pydantic ou check externe). Champs : `error_type`, `check_source` (`None` pour les erreurs Pydantic), `msg`, `ctx` (diagnostic typé, sans fuite d'environnement), `loc`, `relevant_indices` (obligatoire — il porte le ciblage du retry) et `attempt`.

`from_pydantic_error()` convertit une `ValidationError` Pydantic en `ValidationFailure`.

## Checks disponibles

**Répertoire** : [checks/content/](../src/ebook_translator/checks/content/)

| Check | Vérifie | `error_type` | `retry_strategy` | `max_attempts` |
|---|---|---|---|---|
| `LineCountCheck` | Toutes les lignes sont traduites | `LINES_MISSING` | `PROGRESSIVE_REASONING` | 2 |
| `FragmentCountCheck` | Nombre de séparateurs `</>` préservé | `FRAGMENT_COUNT_MISMATCH` | `PROGRESSIVE_REASONING` | 2 |
| `PunctuationCheck` | Équilibre des paires de guillemets | `PUNCTUATION_MISMATCH` | `NORMAL_ONLY` | 2 |
| `SentenceCheck` | Intégrité des phrases | `SENTENCE_INVALID` | `PROGRESSIVE_REASONING` | 2 |

Les quatre sont déclarés par `InitialTranslationPhase` et `RefinementPhase`.

## Registre de retry

**Fichier** : [llm/retry_registry.py](../src/ebook_translator/llm/retry_registry.py)

`RETRY_REGISTRY` associe chaque `ErreursType` corrigeable à une `RetryEntry` :

| `error_type` | Template de correction | Mode de fusion |
|---|---|---|
| `LINES_MISSING` | `retry_translate_missing_lines_targeted` | `merge` |
| `FRAGMENT_COUNT_MISMATCH` | `retry_correct_fragments` | `replace` |
| `PUNCTUATION_MISMATCH` | `retry_correct_punctuation` | `replace` |
| `SENTENCE_INVALID` | `retry_translate_sentence` | `merge` |

`replace` écrase entièrement la ligne (corrections mono-ligne) ; `merge` fusionne au niveau du payload (corrections par lot).

Chaque entrée porte aussi le `TypedDict` des paramètres attendus par le template et la fonction `build` qui compose ces paramètres depuis le diagnostic typé et le `RetryContext` (langue cible, chunk, source, données courantes).

### Erreurs de schéma

`SCHEMA_LEVEL_ERRORS` — `OUTPUT_FORMAT_INVALID`, `MISSING_END_MARKER`, `DUPLICATE_INDICES` — n'ont **pas** d'entrée dans le registre : elles ne se corrigent pas par un retry ciblé, le prompt de phase complet est rejoué. Constantes associées : `SCHEMA_RETRY_STRATEGY = PROGRESSIVE_REASONING`, `SCHEMA_MAX_ATTEMPTS = 2`.

Les diagnostics typés correspondants sont définis dans [validation/diagnostics.py](../src/ebook_translator/validation/diagnostics.py).

## Templates de correction

Les prompts de correction sont dans `template/retry/`, en **paires** `*_system.jinja` + `*_user.jinja` résolues par l'enum `RetryTemplate` :

- `retry_translate_missing_lines_targeted` — lignes manquantes
- `retry_translate_sentence` — phrases tronquées
- `retry_correct_fragments` — fragments `</>`
- `retry_correct_punctuation` — guillemets déséquilibrés
- `retry_correct_analysis_invalid_json`, `retry_correct_analysis_missing_sections` — corrections d'analyse (Phase 0)

Voir [TEMPLATES.md](TEMPLATES.md).

## Retry réseau

**Fichier** : [llm/llm.py](../src/ebook_translator/llm/llm.py)

Indépendamment de la validation, le client gère les erreurs de transport (timeouts, rate limits) avec backoff exponentiel. `max_retries` et `retry_delay` sont configurables via `LLMBuilder`.
