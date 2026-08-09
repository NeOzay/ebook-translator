# Banc : statut vérifié et maîtrise du débit LLM

## Contexte

Dette technique § 10 : `bench/runs/20260804_212523/work/mistral/result.json` porte
`"status": "ok"` avec `chunks_processed: 0` et `llm_calls: 0`. La variante n'a rien
produit, le banc l'a déclarée réussie, et son corpus vide est entré dans l'arbitrage.
Observé 2 fois sur 8 runs Mistral, dans deux états de prompt différents — donc
indépendamment de ce qui était mesuré. Le banc est l'instrument de décision du projet :
tant qu'un run vide passe pour réussi, tout résultat impliquant Mistral doit être relu
à la main avant d'être interprété.

**Ce que la lecture du code a établi**, et qui va au-delà de ce que la dette décrivait :

1. **Le budget d'attente sur 429 est dérisoire.** `LLM.query` (llm.py:152-165) applique
   `retry_delay * 3**attempt` avec `max_retries = 3` : 1 s puis 3 s, soit **4 secondes
   au total** avant abandon définitif. Face à une limite exprimée par minute, ce retry
   ne peut pas réussir — d'où le run vide en 17,7 s.
2. **`Retry-After` n'est jamais lu.** Aucune occurrence dans `src/`. `_translate_error`
   (mistral.py:81) réduit le 429 à `LLMRateLimitError(str(error))` : l'en-tête qui dit
   exactement combien attendre est jeté, alors que `MistralError.headers` l'expose.
3. **Rien n'est partagé entre variantes.** Chaque variante est un sous-processus : un
   limiteur en mémoire repart à zéro à chaque variante. Même dans la boucle séquentielle
   actuelle (runner.py:153), la fin de la variante N et le début de N+1 tombent dans la
   même fenêtre glissante du fournisseur.
4. **La concurrence est plus large qu'il n'y paraît** : `phase.get_worker_count()`
   threads d'executor (executor.py:222) **plus** `num_workers` threads de validation
   (validation_worker_pool.py:61), tous émetteurs d'appels LLM simultanés.

**Déjà soldé, à retirer de la dette** — le sous-point 1 de § 10 (capture des logs par
variante) l'est depuis le chantier `logs-par-run` du 2026-08-05 : `worker.main` appelle
`LogSession.redirect(variant_logs_dir(...))`. La dette n'avait pas été mise à jour.

## Objectif

1. **Ne pas déclencher la limite** — un limiteur de débit partagé entre threads *et*
   entre processus, réglable sur `LLMBuilder`.
2. **Y survivre quand elle tombe quand même** — respect de `Retry-After`, budget de
   retry exprimé en temps, et auto-ajustement AIMD du plafond.
3. **Ne plus jamais présenter un run vide comme réussi** — statut de variante dérivé
   de `chunks_processed`.

**Hors-périmètre** : le `except Exception` large de `PhaseExecutor._process_chunk`
(dette § 9) — un épuisement de retry reste absorbé en perte de chunk ; c'est le statut
du banc (étapes 5-7) qui rend le dégât visible, pas une propagation d'exception.
Également hors périmètre : l'entrée § 7 (`max_retries` qui pilote deux mécanismes).

## Étapes

### 1. `Retry-After` remonté jusqu'à l'appelant — `llm/errors.py`, `clients/mistral.py`

- `LLMRateLimitError` gagne `retry_after: float | None`.
- Extracteur unique `retry_after_seconds(headers: httpx.Headers) -> float | None` :
  les deux SDK exposent des `httpx.Headers` (`MistralError.headers` — vérifié ;
  `openai.RateLimitError.response.headers`). Gérer les deux formes de l'en-tête,
  delta-seconds et date HTTP.
- `_translate_error` (mistral.py:80) le renseigne au lieu de le jeter.

### 2. `RateLimiter` — `src/ebook_translator/llm/rate_limit.py` (nouveau)

Un seul objet, deux verrous superposés — **c'est le point dur** :

```python
class RateLimiter:
    def __init__(self, per_minute: int, provider_key: str, state_dir: Path | None = None): ...
    def acquire(self) -> None:          # réserve le prochain créneau, dort jusqu'à lui
    def penalize(self, retry_after: float | None) -> None:  # AIMD : dégrade
    def record_success(self) -> None:   # AIMD : restaure par paliers
```

- **`threading.Lock` pour les threads, `fcntl.flock` pour les processus.** Les deux
  sont nécessaires : `flock` ne départage pas les threads d'un même processus qui
  partagent un descripteur. Omettre le `Lock` laisserait passer en rafale les
  `worker_count + num_workers` threads du point 4 du contexte.
- **Réservation, pas accumulation de jetons.** Le fichier
  `$XDG_CACHE_HOME/ebook-translator/rate/<provider_key>` contient l'horodatage du
  prochain départ autorisé. Sous les deux verrous : `next = max(read(), now) + interval`,
  on écrit, on relâche, **puis** on dort. Un bucket accumulable ferait repartir ensemble
  tous les threads en attente et reproduirait le 429 qu'on veut éviter.
  Chemin global et non par run : la limite est celle du compte API, elle doit couvrir
  deux bancs concurrents comme un pipeline lancé à côté.
- **AIMD, en mémoire par processus.** Un 429 double l'intervalle courant (plancher :
  `retry_after` s'il est connu), N succès consécutifs le ramènent par paliers vers
  l'intervalle nominal. Chaque processus réserve avec son intervalle courant, donc
  l'ajustement se propage naturellement dans le fichier partagé. Choix assumé : ne pas
  partager le facteur AIMD lui-même, qui demanderait un format d'état versionné.
- `per_minute <= 0` lève, plutôt que de passer silencieusement en illimité.

**Clé de fournisseur** : `provider_key: ClassVar[str]` sur `LLMClientBase`
(clients/base.py:89 a déjà `_api_key_env` comme précédent de ClassVar par provider),
avec repli sur `type(client).__name__.lower()`.

Tests : ≥ 8 threads concurrents prouvés espacés (le test qui porte le chantier) ;
deux processus prouvés espacés via le fichier ; dégradation puis restauration AIMD ;
rejet de `per_minute <= 0`.

### 3. Boucle de retry pilotée par le temps — `llm/llm.py`

La clause 429 (llm.py:152) ne doit plus consommer le compteur `max_retries`, qui
compte des erreurs réseau : `for attempt in range(self.max_retries)` devient une boucle
`while` où **seules les erreurs non-429 incrémentent `attempt`**, les 429 consommant un
budget en secondes (`rate_limit_budget: float = 120.0` sur `LLM`, réglable au builder).
Délai d'attente = `retry_after` si le fournisseur l'annonce, sinon backoff exponentiel
actuel. Les autres clauses (timeout, APIError…) restent inchangées.

`acquire()` est appelé **dans** la boucle, avant `client.request` (llm.py:112) : un
retry après 429 doit reprendre un créneau. Idem dans `json_query` (llm.py:~213).
`penalize` / `record_success` sont branchés sur la clause 429 et sur le retour réussi.

Sans limiteur configuré : comportement actuel à l'identique, hors budget en temps.

**Vérifié** : l'instance de `LLM` est unique pour tout le pipeline — `CommunContext.llm`
est un `ClassVar` (context.py:94), lu par l'executor (executor.py:181/189) et par une
propriété des workers de validation (unified_worker.py:94→96). Le limiteur porté par
cette instance couvre les deux familles de threads sans plomberie à propager. Un client
passé ponctuellement à `query` via `config` (llm.py:104) remplace le client, pas
l'instance : il reste plafonné.

### 4. `LLMBuilder.rate_limit()` — `pipeline/builder.py`

`_rate_limit: int | None`, méthode chaînable, `RateLimiter` construit dans `build()`
(builder.py:152) par appel explicite — pas de `_skip_none` (dette § 3).

```python
LLMBuilder().default_client(Mistral(...)).rate_limit(per_minute=30)
```

Test dans `tests/pipeline/test_builder.py`, qui couvre déjà chaque `add_*`.

### 5. Statut dérivé — `bench/results.py`

- `RunStatus = Literal["ok", "partial", "error"]`.
- `compute_status(phases)` sur les seules phases à `chunks_total > 0` (une phase sans
  travail est neutre) : toutes à `processed == total` → `ok` ; au moins une à
  `0 < processed < total` → `partial` ; toutes à `processed == 0`, ou aucune phase
  retenue → `error`.
- `from_dict` (results.py:186) fait `"ok" if data.get("status") == "ok" else "error"` :
  à élargir, sinon un `partial` relu devient `error`.
- Les phases servies par le seed comptent leurs cache hits dans `chunks_processed` :
  pas de faux positif sur un run amorcé.

### 6. Le worker applique le statut — `bench/worker.py`

Dans `execute` (worker.py:86), `status=compute_status(phases)`, et `error` renseigné
d'un message explicite quand le statut est dégradé (« 0/4 chunks traités — voir
`logs/translation.log` de la variante », désormais présent). `_with_seeded`
(runner.py:204) recopie le statut, rien à changer.

### 7. Rapport et sélection — `bench/runner.py`, `report.py`, `__main__.py`

- `BenchRun` : `succeeded` ne retient que `ok` (déjà le cas), ajouter `partial`.
- `report.py:160` — ratio à côté du statut (`partial — 1/4 chunks`).
- `__main__.py:71` — corpus construit sur `run.succeeded` au lieu de `run.variants`.
  **Défaut existant révélé au passage** : les variantes en échec entrent aujourd'hui
  dans le corpus remis à l'arbitre.
- `__main__.py:80` — signaler les partielles en plus des échecs.

### 8. Vérification

- `uv run pytest --no-cov` vert ; `uv run basedpyright src/` à 0 erreur ;
  `uv run pre-commit run --all-files`.
- **Run réel obligatoire** — le défaut n'a jamais été reproduit en test unitaire.
  Rejouer `bench/config_glossaire.py` sur Mistral **en mode parallèle multi-workers**
  (la configuration qui déclenchait les 429 ; un run séquentiel ne prouverait rien),
  avec `.rate_limit(per_minute=…)` : vérifier `chunks_processed > 0`, `status == "ok"`,
  et l'absence de `🚦 Limite de débit` dans `work/mistral/logs/translation.log`.
- **Croisement inter-processus** : deux variantes successives doivent se partager le
  fichier de créneau — vérifier que la seconde ne redémarre pas en rafale (horodatages
  des `llm_*.log` au changement de variante).
- Un run volontairement étranglé (plafond très bas) doit produire `partial` ou `error`,
  jamais `ok`.

### 9. Documentation

- `docs/TECHNICAL_DEBT.md` — retirer § 10 en entier, en notant que le sous-point 1
  l'était depuis 2026-08-05.
- `docs/BENCH.md` (statuts), `docs/SETUP.md` ou `ARCHITECTURE.md` (réglage de débit et
  fichier d'état partagé), `docs/CHANGELOG.md`.

## Fichiers touchés

| Fichier | Nature |
|---|---|
| `src/ebook_translator/llm/rate_limit.py` | nouveau — limiteur + AIMD + verrou fichier |
| `src/ebook_translator/llm/errors.py` | `retry_after` sur `LLMRateLimitError` |
| `src/ebook_translator/llm/clients/mistral.py` | `_translate_error` renseigne `retry_after` |
| `src/ebook_translator/llm/clients/base.py` | `provider_key: ClassVar[str]` |
| `src/ebook_translator/llm/llm.py` | boucle `while`, budget en temps, `acquire`/AIMD |
| `src/ebook_translator/pipeline/builder.py` | `LLMBuilder.rate_limit` + `build` |
| `src/ebook_translator/bench/results.py` | `RunStatus`, `compute_status`, `from_dict` |
| `src/ebook_translator/bench/worker.py` | statut calculé |
| `src/ebook_translator/bench/runner.py` | `BenchRun.partial` |
| `src/ebook_translator/bench/report.py` | ratio au rapport |
| `src/ebook_translator/bench/__main__.py` | corpus sur `succeeded`, sortie |
| `tests/llm/test_rate_limit.py` | nouveau — threads, processus, AIMD |
| `tests/llm/` (retry) | budget en temps, `Retry-After` |
| `tests/bench/test_results.py`, `test_worker.py`, `test_report.py` | statuts |
| `tests/pipeline/test_builder.py` | `rate_limit` |

## Portabilité

`fcntl.flock` est Unix. La plateforme cible est Linux ; l'absence de `fcntl` doit
dégrader proprement vers le limiteur en mémoire seule, avec un `WARNING`, plutôt que
de faire échouer l'import.
