# Dette technique identifiée

Ce document recense ce qui a été **délibérément laissé de côté**, avec la raison
et ce qu'il faudrait faire pour solder. Il ne liste que de la dette constatée et
vérifiée dans le code — pas des idées d'amélioration : pour celles-ci, voir
[ROADMAP.md](ROADMAP.md).

Chaque entrée indique le chantier qui l'a identifiée. Une entrée soldée est
retirée, pas barrée.

> Dernière vérification : 2026-07-31 (audit du diff de travail).

---

## 1. La couverture de tests ne passe pas son propre seuil

**Constat** — `pyproject.toml` impose `--cov-fail-under=80` dans ses `addopts`.
La couverture réelle est de **72,30 %**. Conséquence directe : `uv run pytest`
**sort en code 1 alors que les 385 tests passent**. C'est la commande
documentée comme *la* façon de lancer les tests.

**Préexistant** : 68,45 % avant le chantier `docs-realignment`, qui a ajouté
27 tests. La dette n'a pas été créée par un chantier, elle s'est accumulée.

**Contournement en place** — `uv run pytest --no-cov` est documenté dans les
deux README ; `CLAUDE.md` explique le seuil et invite à lire le résumé des
tests plutôt que le code de sortie.

**Modules les moins couverts** :

| Module | Couverture |
|---|---|
| `llm/template_params.py` | 0 % |
| `glossary.py` | 15 % |
| `pipeline/executor.py` | 18 % |
| `pipeline/pipeline.py` | 25 % |
| `exporter/glossary_exporter.py` | 28 % |
| `pipeline/store_manager.py` | 33 % |
| `llm/clients/client.py` | 40 % |
| `validation/validation_worker_pool.py` | 61 % |

**Pour solder** — deux voies, exclusives :

- couvrir l'orchestration (`executor.py`, `pipeline.py`, `validation_worker_pool.py`
  concentrent l'essentiel du déficit et sont le cœur du système) ;
- ou ramener le seuil à une valeur tenue, quitte à le remonter par paliers.

Laisser un seuil non tenu est le pire des trois : il rend le signal d'échec
inexploitable.

*Identifié par `docs-realignment`, étape 10.*

---

## 2. `RetryStrategy` est déclaré mais jamais consulté

**Constat** — chaque `ContentCheck` déclare un `retry_strategy` parmi
`NORMAL_ONLY`, `PROGRESSIVE_REASONING` et `REASONING_ONLY`. Le helper
`lookup_strategy()` ([validation/worker_retry.py](../src/ebook_translator/validation/worker_retry.py))
résout cette politique, gère le cas des erreurs de schéma, et est couvert par
les tests.

**Il n'est appelé nulle part en production.** `UnifiedValidationWorker._run_one_retry`
choisit son modèle par `get_model_preset_config("high", attempt_index == max_attempts - 2)`,
avec un commentaire « bascule reasoning T2 (PROGRESSIVE_REASONING) déférée
Step 4c ». La politique par check n'a donc aucun effet : tous les checks
basculent en thinking à l'avant-dernière tentative, quelle que soit leur
déclaration.

**Pourquoi c'est gênant** — `PunctuationCheck` déclare `NORMAL_ONLY` et passe
malgré tout en thinking. Le code affirme une intention que l'exécution
contredit.

**Documenté** comme écart connu dans [VALIDATION.md](VALIDATION.md).

**Pour solder** — brancher `lookup_strategy()` dans `_run_one_retry`, ou
retirer `retry_strategy` de `ContentCheck` et le helper avec. La seconde voie
est plus honnête si la politique par check n'a pas d'usage prévu.

*Identifié par `docs-realignment`, étape 3.*

---

## 3. Le déballage `**kwargs` masque encore les appels du builder

**Constat** — `_skip_none(**overrides) -> dict[str, Any]`
([pipeline/builder.py](../src/ebook_translator/pipeline/builder.py)) reste
utilisé à **7 endroits**. Un `dict[str, Any]` déballé dans un appel rend
basedpyright aveugle aux arguments inexistants.

**Ce n'est pas théorique** : ce motif a produit **quatre bugs** dans l'API
publique, tous invisibles au type-checker et tous fatals à l'exécution —
`LLM(model_name=…)`, `GlossaryPhase(overrides=…)`, `Phase(llm_config=…)` sur
les quatre phases, et un `build()` qui levait `AttributeError`. Ils ont été
corrigés, mais le motif qui les a permis subsiste.

**Atténuation en place** — `tests/pipeline/test_builder.py` couvre désormais
chaque `add_*` et chaque champ requis, y compris un test qui compare les clés
de `run_kwargs` à la signature réelle de `Pipeline.run`. Une régression du même
type serait attrapée par les tests, plus par le typage.

**Pour solder** — remplacer les `_skip_none` par des appels explicites, comme
cela a été fait pour `LLMBuilder.build()` : porter les defaults dans le
builder plutôt que de filtrer des `None`.

*Identifié par `docs-realignment`, étape 1.*

---

## 4. Écarts entre le refactor `PhaseBase` et sa cible

Le plan du refactor, archivé dans
`.claude/implementation/done/2026-07-30-refactor-phasebase.md`, annonçait huit
critères de validation. Quatre ne sont pas tenus. Les deux premiers sont des
décisions d'architecture assumées en cours de route ; les deux autres sont de
la dette réelle.

**Décisions assumées, à ne pas « corriger »** :

- `InstructorConfig[M]` n'a jamais été créé — `JsonRequestConfig` a été
  conservé et porte la voie Instructor.
- `Store[M]` typé par phase n'existe pas. Le typage est passé à
  `ChunkPersister` + `ByteStore` + `PhaseStorage`, découpe qui s'est révélée
  meilleure. `Store` reste non générique.

**Dette réelle** :

- Le critère « aucune occurrence de `dict[int, str]` dans `pipeline/`,
  `validation/`, `stores/` » n'est pas atteint : **6 occurrences** subsistent,
  concentrées sur le chemin de retry (`RetryContext.current_data`,
  `WorkerRetryContext.current_data`) et dans la lecture legacy de `Store`. Le
  pivot vers `DT` typé s'est arrêté avant ce chemin.
- `LineIndexedTranslation` a été renommé `LineIndexedLLMResponse` sans que le
  plan soit mis à jour — sans conséquence, mais signe que le document avait
  cessé de suivre le code bien avant son archivage.

*Identifié par `docs-realignment`, étape 7.*

---

## 5. Template orphelin dans le submodule

**Constat** — `template/common/literary_context_layered_block.jinja`
(77 lignes) n'a **aucun référent**, ni dans `src/ebook_translator/`, ni dans
les autres templates.

C'est vraisemblablement le pendant stratifié de `literary_context_block.jinja`,
écrit pour injecter un `AnalyseChapter` dans les prompts de traduction, mais
jamais branché : les phases 1 et 2 incluent toujours la version non stratifiée.

**Hors-périmètre** du chantier qui l'a trouvé — le submodule `template` a son
propre dépôt et sa propre documentation.

**Pour solder** — dans un chantier dédié au submodule : le brancher (si
l'injection stratifiée est souhaitée) ou le supprimer.

*Identifié par `docs-realignment`, étape 3.*

---

## 6. Le glossaire est peuplé depuis un hook asynchrone

**Constat** — `GlossaryPhase.on_save()` appelle `_populate_glossary()`. `on_save`
est exécuté par le `SaveWorker`, sur son propre thread. L'executor, lui,
n'attend pas : il peut rendre le prompt du chunk N+1 — qui embarque
`context.glossary` — avant que le `SaveWorker` ait traité le chunk N.

Deux conséquences :

- **Non-déterminisme** — les termes visibles d'un chunk donné dépendent de la
  charge. Deux runs sur le même livre peuvent produire des prompts différents.
- **Échec silencieux** — `SaveWorker` enveloppe `on_save` dans un
  `except Exception` → `logger.warning`. Une exception dans `learn()` n'échoue
  plus le chunk : le glossaire est amputé sans signal.

**Assumé** : le choix garantit que seul du contenu validé et persisté alimente
le glossaire. `after_response`, synchrone dans le thread de l'executor, offrait
la garantie inverse — visibilité immédiate, mais apprentissage sur donnée non
encore validée.

**Pour solder** — si la visibilité immédiate redevient nécessaire : repasser le
seul `_populate_glossary()` dans `after_response` et laisser l'export Markdown
dans `on_save`, ou attendre le drainage de la `SaveQueue` entre deux chunks de
la phase glossaire (coûteux, elle est déjà séquentielle).

*Identifié par l'audit du 2026-07-31.*

---

## 7. `LLM.max_retries` pilote deux mécanismes différents

**Constat** — la même valeur (défaut 3) règle deux politiques sans rapport :

| Chemin | Ce que compte `max_retries` | Coût d'une tentative |
|---|---|---|
| `LLM.query()` | retries réseau/API, avec backoff exponentiel | un appel |
| `LLM.json_query()` → `client.json_request(…, max_retries)` → `instructor.create_with_completion()` | corrections de schéma : l'erreur Pydantic est réinjectée dans la conversation | un appel, prompt cumulé |

Une erreur réseau et un `maxItems` dépassé n'appellent pas le même nombre de
tentatives, et la seconde coûte des tokens croissants à chaque passe. Il n'y a
aujourd'hui aucun moyen de régler l'une sans l'autre.

**Pourquoi c'est gênant** — remonter la tolérance réseau à 5 multiplie
silencieusement les corrections de schéma payantes ; l'inverse rend le pipeline
fragile aux coupures pour économiser des retries de validation.

**Assumé** : le câblage a été fait en propageant la valeur existante plutôt
qu'en ouvrant un nouveau réglage public, pour ne pas élargir l'API des builders
avant d'avoir mesuré le besoin.

**Pour solder** — un `schema_max_retries` distinct sur `LLM` et
`LLMBuilder`, avec `max_retries` comme valeur de repli. La signature
`ClientProviderProtocol.json_request(…, max_retries)` est déjà en place, seul
l'appelant décide.

*Identifié par l'audit du 2026-07-31.*

---

## 8. Points mineurs, laissés sciemment

- `frozen_static.is_frozen()` n'a aucun appelant en production. Conservé :
  accesseur public cohérent d'un module utilitaire, couvert par les tests.
- `LiteraryAnalysisPhase.head_tail_balance` vaut `0` (entier) là où
  l'annotation est `float`, contrairement à `overlap_ratio: float = 0.0` juste
  au-dessus. Purement cosmétique.
- `docs/CHANGELOG_ARCHIVE.md` contient une cinquantaine de liens cassés vers
  des fichiers supprimés depuis. **Volontaire** : un changelog documente le
  code tel qu'il était, son entête le dit.
