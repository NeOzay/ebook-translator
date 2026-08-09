# Banc d'essais comparatif de pipelines

Comparer plusieurs configurations de pipeline sur un même livre — modèle, température,
composition des phases, segmentation — et faire arbitrer le résultat en aveugle par un
agent Claude.

```bash
uv run ebook-bench bench/config_exemple.py
# puis, dans Claude Code :
/bench-judge
```

## Ce que produit un run

```
bench/runs/<run_id>/
  README.md              # protocole de lecture, remis à l'arbitre
  metrics.md             # durée, appels LLM, tokens, chunks rejetés — par variante et par phase
  compare/
    translation/NN-<fichier>.md   # source ↔ variantes, fragment par fragment
    glossary.md                   # glossaires de revue confrontés
    analysis.md                   # fiches d'analyse littéraire confrontées
  manifest.json          # étiquette → variante → paramètres
  verdict.md             # écrit par l'arbitre
  config.py              # copie du script de configuration
  work/<variant_id>/     # workspace brut : cache, EPUB produit, result.json
```

Dans `metrics.md` et `compare/`, les variantes ne portent que des étiquettes `A`, `B`,
`C`. Le lien avec les paramètres n'existe que dans `manifest.json`, que l'arbitre
n'ouvre qu'après avoir conclu. L'attribution des étiquettes est un mélange déterministe
seedé sur le `run_id` : reproductible, mais indépendant de l'ordre de déclaration.

## Écrire une configuration

Un script Python exposant `suite = BenchSuite(...)`. Il garde toute l'expressivité des
builders — voir [bench/config_exemple.py](../bench/config_exemple.py).

```python
def pipeline(env: RunEnv, model: DeepseekModels, temperature: float) -> PipelineBuilder:
    return (
        PipelineBuilder()
        .epub(env.epub)            # ← les trois chemins du RunEnv
        .output(env.output)        #   doivent être relayés tels quels
        .cache_dir(env.cache_dir)
        .language(Language.FRENCH)
        .llm(LLMBuilder().default_client(Deepseek(model, config={"temperature": temperature})))
        .phases(PhasesBuilder().add_literary_analysis().add_initial_translation())
    )


suite = BenchSuite(
    epub=Path("books/The Yellow Wallpaper.epub"),
    seed=Seed(
        build=lambda env: pipeline(env, DeepseekModels.FLASH, 0.5),
        phases=(PhaseName.LITERARY_ANALYSIS,),
    ),
    variants=[
        Variant("t05", {"temperature": 0.5}, lambda env: pipeline(env, DeepseekModels.FLASH, 0.5)),
        Variant("t10", {"temperature": 1.0}, lambda env: pipeline(env, DeepseekModels.FLASH, 1.0)),
    ],
    corpus=CorpusOptions(max_fragments=60),
)
```

`params` est de la métadonnée pure : elle nourrit le manifeste, jamais le corpus remis
à l'arbitre. Elle n'agit pas sur le pipeline — c'est la fabrique qui décide.

### Relayer le `RunEnv` est obligatoire

Une fabrique qui code en dur son EPUB ou son cache ferait fuiter les variantes les unes
dans les autres : caches croisés, glossaires écrasés, comparaison sans valeur. Le
harness vérifie les deux chemins après construction du pipeline et refuse de lancer
sinon.

### Phases partagées

`Seed` fait tourner un run d'amorçage avant les variantes, puis **copie** les stores des
phases listées dans le cache de chacune. Ces phases sont alors servies depuis le cache :
aucun appel LLM, et un résultat rigoureusement identique partout. C'est ce qui permet
d'attribuer un écart de traduction à la température plutôt qu'à une analyse littéraire
qui aurait dérivé.

Vérification dans `metrics.md` : la phase partagée doit afficher `cache = chunks` et
`appels LLM = 0` pour toutes les variantes.

La copie est délibérée — un symlink laisserait une variante corrompre la référence
commune si elle recalculait une partie de la phase.

### Faire varier le glossaire de départ

Comparer des pipelines suppose parfois de faire varier non pas un réglage, mais l'**état
initial** que la phase reçoit. Le cas type est le glossaire : à froid, il reste instable
pendant l'essentiel du livre, puisqu'il faut cinq émissions unanimes pour qu'un terme
converge. Les trois groupes du prompt ne sont donc réellement peuplés qu'à la fin.

`PipelineBuilder.glossary(...)` et `.glossary_seed(...)` permettent de partir d'un
glossaire hérité d'un tome précédent ou d'un seed déclaratif — voir
[bench/config_glossaire_seed.py](../bench/config_glossaire_seed.py), qui oppose un run à
froid à un run prérempli.

Dans ce cas, la phase glossaire ne doit **surtout pas** figurer dans les phases partagées
du `Seed` : elle est l'objet de la comparaison. Ne partager que l'analyse littéraire.

## Options de corpus

| Option | Défaut | Effet |
| --- | --- | --- |
| `translation` | `True` | Comparaison fragment à fragment des traductions |
| `glossary` | `True` | Glossaires de revue exportés par la phase glossaire |
| `analysis` | `True` | Fiches `AnalyseChapter` exportées par la Phase 0 |
| `max_fragments` | `120` | Plafond de fragments retenus **par fichier HTML** |
| `include_identical` | `False` | Conserver les fragments rendus à l'identique partout |

Les fragments identiques sont écartés par défaut : ils ne départagent rien et diluent le
corpus. Leur nombre reste reporté dans `README.md`.

## Ligne de commande

```bash
uv run ebook-bench <config.py> [options]

  --runs-dir DIR   Répertoire des runs (défaut : bench/runs)
  --run-id ID      Identifiant du run (horodaté par défaut)
  --only a,b       N'exécuter que ces variantes
```

`ebook-bench` est déclaré en `[project.scripts]`. La forme longue reste équivalente et
fonctionne sans installation du paquet :

```bash
uv run python -m ebook_translator.bench <config.py>
```

Code de sortie 1 si une variante a échoué — le run se poursuit malgré tout, les autres
variantes gardent leur intérêt. Un échec du run d'amorçage arrête tout : les variantes
en dépendent.

## Arbitrage

`/bench-judge [run_id]` délègue à l'agent `bench-judge`
([.claude/agents/bench-judge.md](../.claude/agents/bench-judge.md)), qui démarre à
contexte vide. C'est ce qui rend l'aveugle réel : le juge ignore quels paramètres ont
été essayés et lesquels ont la faveur de l'utilisateur.

Il note chaque variante sur fidélité, fluidité, cohérence terminologique, registre et
artefacts, écrit `verdict.md` avec extraits à l'appui, arbitre qualité contre tokens,
puis lève l'anonymat en fin de fichier.

## Notes d'architecture

- **Un sous-processus par variante.** `CommunContext` est un `FrozenStatic` gelé au
  premier `Pipeline.run()` et `HtmlPage` est un singleton par item : deux runs dans un
  même processus sont impossibles.
- **Exécution séquentielle.** Des variantes concurrentes se disputeraient le débit de
  l'API et leurs durées ne seraient plus comparables.
- **Alignement du corpus.** `HtmlPage.dump()` réattribue les mêmes index de fragment que
  pendant le run ; les stores de phase donnent `{index: traduction}`. La comparaison se
  reconstruit donc sans rejouer le pipeline. Les phases tardives écrasent les
  précédentes, comme à la reconstruction de l'EPUB.
- **Tokens.** `UsageMeter` ([llm/usage.py](../src/ebook_translator/llm/usage.py)) agrège
  les compteurs de `LLMResponse` par phase ; `PhaseExecutor` les reporte dans
  `PhaseStats.usage`. Le compteur tourne pour tous les runs, pas seulement le banc
  d'essais.

## Limites connues

- Pas de conversion tokens → euros : aucune table de prix par provider n'est tenue.
- Les logs du pipeline partent dans `logs/run_<horodatage>/` du répertoire courant, un
  répertoire par sous-processus, hors du workspace de la variante.
- L'EPUB source n'est pas sous-échantillonné : préférer un livre court pour un banc
  d'essais, ou plafonner le corpus rendu avec `max_fragments`.
