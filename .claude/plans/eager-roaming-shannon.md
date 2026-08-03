# Banc d'essais comparatif de pipelines

## Contexte

Le pipeline expose une dizaine de paramètres qui changent le résultat (modèle, `temperature`,
`max_tokens`, `overlap_ratio`, composition des phases, workers). Aujourd'hui rien ne permet de
répondre à « est-ce que ce réglage traduit mieux que l'autre, et à quel coût ». Les seules traces
sont les logs de session et un `PhaseStats` qui ne compte ni les tokens ni les appels LLM.

But : un harness qui exécute N variantes d'un même livre, isole leurs caches, et produit un corpus
comparatif **anonymisé** que Claude Opus juge via un skill dédié.

Deux contraintes structurantes relevées à l'exploration :

- `CommunContext` est un `FrozenStatic` (`frozen_static.py`) gelé au premier `Pipeline.run()`, et
  `HtmlPage` est un singleton par `EpubHtml`. **Un seul run par processus** → chaque variante
  s'exécute dans un sous-processus.
- Un chunk servi par le cache repasse par `after_response` puis `on_save`
  ([executor.py:142](src/ebook_translator/pipeline/executor.py#L142)). Une phase entièrement en
  cache reconstruit donc son état mémoire (fiches d'analyse, glossaire) sans appel LLM — c'est ce
  qui rend le partage de phase possible.

## Périmètre

**But** : comparer des variantes de pipeline sur traduction, glossaire et analyse littéraire, avec
métriques de coût, et faire arbitrer par Claude en aveugle.

**Critères de réussite** :

- `uv run python -m ebook_translator.bench bench/config_exemple.py` produit
  `bench/runs/<run_id>/` complet (métriques + corpus comparatif + manifeste).
- Deux variantes partageant une phase produisent des sorties identiques pour cette phase, sans
  appel LLM supplémentaire (vérifiable : `chunks_from_cache == chunks_total`, `llm_calls == 0`).
- `/bench-judge <run_id>` lance l'agent arbitre, qui rend un verdict argumenté sans avoir lu le
  manifeste avant de conclure.
- `uv run basedpyright src/` → 0 erreur ; tests du nouveau module au vert.

**Hors-périmètre** (à confirmer) :

- Conversion tokens → euros (pas de table de prix par provider ; les tokens bruts suffisent).
- Exécution concurrente de plusieurs variantes (séquentiel : les mesures de durée resteraient
  incomparables sous contention API).
- Sous-échantillonnage de l'EPUB source (on choisit un petit livre, ex. `The Yellow Wallpaper`).
- Modification des phases existantes ou de leur logique de cache.
- Intégration CI.

## Architecture

```
src/ebook_translator/bench/
  suite.py      # BenchSuite, Variant, RunEnv + chargement du script utilisateur
  usage.py      # UsageMeter (accumulateur de tokens)
  workspace.py  # isolation par variante + amorçage des phases partagées
  runner.py     # orchestration séquentielle, subprocess par variante
  worker.py     # point d'entrée enfant : construit et exécute UNE variante
  collect.py    # extraction du corpus depuis le workspace
  report.py     # manifeste + métriques + corpus comparatif anonymisé
  __main__.py   # CLI
bench/
  config_exemple.py
  runs/<run_id>/…          (gitignoré)
.claude/skills/bench-judge/SKILL.md
```

### Configuration utilisateur

Le script utilisateur est un module Python chargé par `importlib.util.spec_from_file_location`, qui
expose `suite: BenchSuite`. Il garde toute l'expressivité des builders existants
([builder.py](src/ebook_translator/pipeline/builder.py)) :

```python
def base(env: RunEnv, model, temp) -> PipelineBuilder:
    return (
        PipelineBuilder()
        .epub(env.epub).output(env.output).cache_dir(env.cache_dir)
        .language(Language.FRENCH)
        .llm(LLMBuilder().default_client(Deepseek(model, config={"temperature": temp})))
        .phases(PhasesBuilder().add_literary_analysis(max_tokens=5000)
                              .add_initial_translation()
                              .add_refinement())
    )

suite = BenchSuite(
    epub=Path("books/The Yellow Wallpaper.epub"),
    seed=Seed(build=lambda env: base(env, DeepseekModels.FLASH, 0.5),
              phases=(PhaseName.LITERARY_ANALYSIS,)),   # phase figée, partagée
    variants=[
        Variant("v1", params={"model": "flash", "temperature": 0.5},
                build=lambda env: base(env, DeepseekModels.FLASH, 0.5)),
        Variant("v2", params={"model": "flash", "temperature": 1.0},
                build=lambda env: base(env, DeepseekModels.FLASH, 1.0)),
    ],
)
```

`params` n'est que de la métadonnée : elle alimente le manifeste, jamais le corpus anonymisé.

### Isolation et phases partagées

Un workspace par variante : `runs/<run_id>/work/<variant_id>/`, contenant un **symlink** vers
l'EPUB source. `Pipeline._glossary_export_path` et le `cache_dir` par défaut dérivent tous deux de
`epub_path.parent` — le symlink suffit à confiner les écritures, sans copier le livre.

Phase partagée : le seed s'exécute d'abord dans son propre workspace ; pour chaque variante, les
répertoires `<seed_cache>/<store_key>/` des phases listées dans `Seed.phases` sont **copiés** dans
le cache de la variante avant lancement (`store_key()` = nom de phase,
[base.py:474](src/ebook_translator/pipeline/base.py#L474)). Copie plutôt que symlink : une variante
qui recalculerait une partie de la phase corromprait sinon la référence commune.

### Mesure des tokens

`LLMResponse` porte déjà `prompt_tokens` / `completion_tokens` / `cached_tokens` /
`reasoning_tokens` ([llm_config.py:83](src/ebook_translator/llm/llm_config.py#L83)) mais rien ne les
agrège. Ajouts :

- `bench/usage.py` : `UsageMeter`, accumulateur thread-safe indexé par nom de phase, avec un
  attribut `current_phase`.
- `LLM.query` et `LLM.json_query` ([llm/llm.py](src/ebook_translator/llm/llm.py)) enregistrent la
  `LLMResponse` dans `self.usage` (les deux voies passent par `client.request` /
  `client.json_request` qui la retournent). Meter inactif par défaut → coût nul hors banc d'essais.
- `PhaseExecutor.run` pose `context.llm.usage.current_phase = self.phase.name`. Les phases sont
  séquentielles et les retries des workers de validation restent dans la phase courante
  (`wait_completion` en fin de phase) : l'attribution est sûre.
- `PhaseStats` gagne `llm_calls`, `prompt_tokens`, `completion_tokens`, `cached_tokens`,
  `reasoning_tokens`, remplis en fin de phase depuis le meter.

### Collecte du corpus

- **Traduction** : `HtmlPage.dump()` ([page.py:80](src/ebook_translator/htmlpage/page.py#L80)) rend
  des `(TagKey, texte source)` avec un `index` déterministe ; les stores de phase rendent
  `{index: traduction}` via `Store.get_from_file`. On aligne source ↔ variantes par index, dans
  l'ordre du spine. Fragments identiques sur toutes les variantes : exclus du corpus (bruit), mais
  comptés dans les métriques.
- **Glossaire** et **analyse** : les phases exportent déjà du Markdown de revue dans leur store
  ([glossary.py:144](src/ebook_translator/pipeline/phases/glossary.py#L144),
  [literary_analysis.py:184](src/ebook_translator/pipeline/phases/literary_analysis.py#L184)). La
  collecte les reprend tels quels — pas de nouvel exporteur.

### Sortie destinée à Claude

```
runs/<run_id>/
  README.md              # protocole de lecture pour le juge
  metrics.md             # table A/B/C : durée, chunks, rejets, tokens, appels
  compare/
    translation/<fichier>.md   # Source / A / B / C par fragment divergent
    glossary.md
    analysis/<chapitre>.md
  manifest.json          # A → v1{model, temperature, …}  ← lu APRÈS le verdict
  work/<variant_id>/     # workspace brut (caches, EPUB produit, logs)
```

Les labels `A/B/C` sont attribués par un mélange déterministe (seed = `run_id`) : ni l'ordre de
déclaration ni l'ordre alphabétique ne trahissent la variante.

### Arbitre : agent dédié, piloté par un skill

L'arbitrage tourne dans un **agent** (`.claude/agents/bench-judge.md`, modèle Opus) et non dans la
conversation principale : contexte propre, donc aucune contamination par l'historique
d'implémentation, et le corpus (volumineux) ne pollue pas la session de l'utilisateur. C'est aussi
ce qui rend l'aveugle réel — l'agent démarre à froid et ne connaît des variantes que ce que
`compare/` lui montre.

Le skill `.claude/skills/bench-judge/SKILL.md` est le point d'entrée `/bench-judge [run_id]` : il
résout le `run_id` (dernier run si omis), vérifie que `verdict.md` n'existe pas déjà, puis lance
l'agent `bench-judge` sur ce répertoire et restitue la synthèse.

L'agent :

1. Lit `README.md`, `metrics.md`, puis les fichiers de `compare/`. Interdiction explicite d'ouvrir
   `manifest.json` avant l'étape 4.
2. Note chaque variante par critère : fidélité, fluidité, cohérence terminologique, registre/style,
   artefacts (fragments manquants, `</>` non préservés, texte resté en langue source).
3. Écrit `verdict.md` : classement, justification appuyée sur des fragments cités, arbitrage
   qualité/tokens à partir de `metrics.md`.
4. Lit `manifest.json` et ajoute la levée d'anonymat en fin de `verdict.md`.

Outils de l'agent restreints à `Read`, `Grep`, `Glob`, `Write` : pas de Bash, pas de réseau — il
ne peut ni relancer un run ni contourner l'aveugle.

## Étapes

- [ ] 1. `UsageMeter` + instrumentation `LLM` / `PhaseExecutor` / `PhaseStats` — `bench/usage.py`,
      `llm/llm.py`, `pipeline/executor.py`, `pipeline/context.py` (+ tests)
- [ ] 2. Modèle de configuration — `bench/suite.py` (`BenchSuite`, `Variant`, `Seed`, `RunEnv`,
      chargement du script utilisateur)
- [ ] 3. Isolation et amorçage — `bench/workspace.py` (symlink EPUB, copie des phases partagées)
- [ ] 4. Exécution — `bench/worker.py` (enfant) + `bench/runner.py` (orchestration, `stats.json`)
- [ ] 5. Collecte du corpus — `bench/collect.py` (traduction alignée, glossaire, analyse)
- [ ] 6. Rendu — `bench/report.py` (`manifest.json`, `metrics.md`, `compare/`, `README.md`)
- [ ] 7. CLI + exemple — `bench/__main__.py`, `bench/config_exemple.py`, entrée `.gitignore`
- [ ] 8. Arbitre — agent `.claude/agents/bench-judge.md` + skill de lancement
      `.claude/skills/bench-judge/SKILL.md`
- [ ] 9. Documentation — `docs/BENCH.md`, renvois depuis `CLAUDE.md`

## Vérification

```bash
uv run basedpyright src/                      # 0 erreur
uv run pytest tests/bench --no-cov            # unitaires (workspace, collect, report, usage)
uv run python -m ebook_translator.bench bench/config_exemple.py   # bout en bout, 2 variantes
```

Bout en bout attendu : `bench/runs/<run_id>/` peuplé ; dans `metrics.md`, la phase partagée affiche
`llm_calls = 0` et `cache 100 %` pour toutes les variantes ; `compare/analysis/` est identique
entre variantes. Puis `/bench-judge <run_id>` → `verdict.md` avec levée d'anonymat en fin de fichier.
