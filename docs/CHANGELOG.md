# Historique des versions

> Ce fichier démarre à la version 0.12.0.
> Pour les versions 0.2.0 à 0.11.0 (2025-10-19 → 2025-11-15), voir
> [CHANGELOG_ARCHIVE.md](CHANGELOG_ARCHIVE.md) — les symboles qui y sont cités
> décrivent le code de l'époque et beaucoup n'existent plus.
> Pour les améliorations futures planifiées, voir [ROADMAP.md](ROADMAP.md).

## Récapitulatif des versions

| Version | Date | Fonctionnalité principale | Impact |
|---------|------|---------------------------|--------|
| *Non publié* | — | *Hooks de phase dédoublés, routage des workers par phase, glossaire source en lecture seule, sortie glossaire tabulaire, sélection du glossaire, plafond de débit LLM et statut de variante vérifié, `template` absorbé* | *3 effets de bord, voir ci-dessous* |
| **0.12.0** | **2026-07-30** | **Pivot TypedDict, persistance stratifiée, validation unifiée** | **-8274 lignes, 9 bugs corrigés** |

---

## Non publié

### 🧹 `template` n'est plus un sous-module git

`src/template/` était un dépôt distinct monté en sous-module. Le pointeur devait
être resynchronisé à chaque merge, pour un contenu qui n'a jamais servi ailleurs
que dans ce dépôt. Le coût de coordination dépassait le bénéfice : un checkout
resté en arrière suffisait à faire régresser les tests sans que rien ne le
signale — c'est exactement ce qui est arrivé lors de l'absorption, l'arbre de
travail pointant un ancêtre qui annulait la préservation de casse des traductions
proposées.

Le contenu est désormais versionné dans le dépôt principal, figé sur `23865dc`.
L'historique du sous-module reste consultable sur `NeOzay/ebook-translator-template`.
Plus rien à faire au clone : ni `--recursive`, ni `git submodule update`.

### 🚦 Maîtrise du débit LLM et statut de variante vérifié

#### Un run de banc vide ne peut plus passer pour réussi

Le statut d'une variante est désormais **dérivé** de `chunks_processed` au regard de
`chunks_total` (`compute_status`, [bench/results.py](../src/ebook_translator/bench/results.py))
et prend trois valeurs : `ok`, `partial`, `error`. Il était auparavant écrit `"ok"` dès
que le pipeline rendait la main sans exception — un run étranglé par le débit, à zéro
chunk, était donc déclaré réussi et son corpus vide entrait dans l'arbitrage.

Les chunks servis par le cache comptent comme traités : un run amorcé par un `Seed`
reste `ok`. Le corpus d'arbitrage se construit sur `run.succeeded` — **les variantes en
échec y entraient jusqu'ici**. `metrics.md` affiche le ratio à côté d'un statut dégradé.

#### Plafond de débit partagé entre threads et entre processus

`LLMBuilder.rate_limit(per_minute)` plafonne les appels à un provider. Le créneau est
réservé dans un fichier verrouillé (`flock`) sous `$XDG_CACHE_HOME/ebook-translator/rate/`,
donc partagé par les threads d'executor, ceux du pool de validation, les sous-processus
de variantes d'un banc et deux bancs concurrents. Un limiteur en mémoire seule serait
reparti à zéro à chaque variante.

La réservation espace les *départs* au lieu d'accumuler des jetons : un « token bucket »
classique relâche d'un coup tous les threads en attente et reproduit la rafale.
`per_minute` est un flottant — `mistral-large-2512` annonce 0,07 req/s, soit 4,2/min.

#### Un 429 ne consomme plus une tentative réseau, mais du temps

`LLM.query` et `LLM.json_query` séparent deux politiques : `max_retries` compte les
erreurs réseau, tandis qu'une limite de débit consomme `rate_limit_budget` (120 s par
défaut). L'ancienne boucle accordait `retry_delay * 3**attempt` sur 3 tentatives, soit
**4 secondes au total** — insuffisant par construction face à un quota par minute.

`Retry-After` est lu quand le provider le fournit (`LLMRateLimitError.retry_after`) ;
Mistral n'en envoie pas. À défaut, backoff plafonné à 30 s par attente. Un 429 divise
le débit par deux et repousse le créneau **pour tous les émetteurs**, puis une série de
succès le regagne par paliers.

**Vérifié en conditions réelles** (2026-08-09, `The Yellow Wallpaper`, phase glossaire,
deux runs simultanés × deux variantes Mistral à 4,2/min et `.workers(2)`) : 4 variantes
en `ok`, 4/4 chunks chacune, 16 échanges entrelacés entre les 4 sous-processus et
espacés de 11 à 17 s autour de la cible de 14,3 s. L'unique 429 a été absorbé, son chunk
traité.

Solde l'entrée *« Un run de banc étranglé par le débit passe pour réussi, sans trace »*
de [TECHNICAL_DEBT.md](TECHNICAL_DEBT.md), dont le premier des trois défauts (capture
des logs par variante) l'était depuis le 2026-08-05.

### ✨ Sélection du glossaire et mesure par phase

#### La phase glossaire sélectionne au lieu de balayer

`glossary_system.jinja` remplace sa puce de couverture par catégories — « le
glossaire doit couvrir : personnages, lieux, créatures… » — par des conditions
d'admission cumulatives, une liste d'exclusion et une dérogation pour les noms
propres. L'ancienne consigne disait *comment ranger* un terme, jamais *s'il
fallait le retenir*.

Les conditions portent sur le **bloc courant** et sur le glossaire réinjecté :
chaque appel LLM est isolé, un critère qui parle du livre entier est
invérifiable. La colonne `terme` porte désormais une forme canonique sans
déterminant.

Sur *The Yellow Wallpaper*, 48 termes deviennent 19 (DeepSeek) et 14 (Mistral)
sans qu'aucune entité nommée disparaisse. `the yellow wallpaper`, émis sous
trois clés de poids 1, devient une clé unique de poids 4.

#### La réinjection montre tous les termes du bloc

`collect_entry_with_conflicts` ne filtre plus par poids. Le seuil
`DEFAULT_MIN_REINJECTION_WEIGHT` décide maintenant du **détail montré**, pas de
la visibilité : au-delà, le terme et ses propositions pondérées ; en deçà, sa
seule forme. Un terme trop léger restait invisible au LLM, qui le réémettait
sous une variante divisant encore son poids.

`GlossaryParams` porte le seuil ; le partage en trois groupes se fait dans
`glossary_existing_block.jinja`.

#### Le glossaire ne minuscule plus les propositions de traduction

`Glossary.learn` continue de compter sur la forme minuscule — `Jean` et `jean`
sont la même proposition et doivent cumuler leur poids — mais mémorise les
graphies observées et restitue la dominante. Les phases 1 et 2 recevaient
jusqu'ici un glossaire d'anthroponymes en bas de casse.

Cache rétrocompatible : un glossaire écrit sans `translation_casing` se relit et
rend la forme minuscule, comme avant.

#### L'audit voit les clés concurrentes

Nouvelle catégorie `variantes-de-surface` : des clés distinctes qui désignent le
même élément, chacune individuellement cohérente, donc invisible à toute autre
catégorie. `nom-commun-article` retient l'article de la clé **ou** celui de la
source, faute de quoi la forme canonique le rendrait aveugle.

`redondance` et « Termes convergés » passent en limite de mesure quand le livre
compte moins de chunks que le poids de convergence : aucun terme ne pouvant
alors converger, leur zéro n'était pas un constat.

### ⚡ Breaking Changes

#### 0. La phase glossaire produit un tableau délimité, plus du JSON

`LLMGlossaryModel` ne décrit plus `{"colonnes": [...], "entrees": [[...]]}` : le
LLM répond une ligne par terme, quatre colonnes séparées par `|`, terminée par
`[=[END]=]`.

```
Alice|personnage|f|Alice
White Rabbit|creature|m|Lapin Blanc
[=[END]=]
```

À structure égale, l'enveloppe JSON coûtait deux fois plus de tokens **de
sortie** par entrée — les plus chers et les seuls non cacheables. Mesuré à
`cl100k_base` sur un chunk de 30 entrées :

| | avant | après | delta |
|---|---:|---:|---:|
| Entrée par appel (prompt système + schéma injecté) | 1335 | 1024 | −23 % |
| Sortie par appel (30 entrées) | 800 | 394 | −51 % |

Conséquences :

- `GlossaryPhase.get_llm_config()` disparaît : la phase passe par `LLM.query()`
  et non plus par Instructor. `LLMGlossaryModel` parse la chaîne brute dans un
  validateur `mode="before"`, comme `LineIndexedLLMResponse`.
- Le champ `colonnes` est supprimé du modèle — l'ordre est porté par le format.
  `GLOSSARY_COLUMNS` reste exposé pour la documentation du prompt.
- **Le format de cache est inchangé** (JSON, via `MemoizedChunkPersister`) : les
  caches de glossaire existants restent lisibles.
- Une ligne dont la cardinalité n'est pas 4, ou dont `type`/`sexe` sort des
  valeurs autorisées, est écartée avec un `WARNING` au lieu de déclencher une
  correction ; les puces en tête de ligne sont nettoyées. Seules la génération
  tronquée et la réponse dont aucune ligne n'est exploitable font échouer le
  chunk.

#### 1. `PhaseBase.after_chunk()` devient `after_response()`, et `on_save()` apparaît

Le hook unique post-chunk est scindé en deux, selon le moment et le thread :

| Hook | Thread | Donnée reçue | Échec |
|------|--------|--------------|-------|
| `after_response(chunk, data, context)` | executor | validée par le schéma, **avant** les `content_checks` | remonte, le chunk échoue |
| `on_save(chunk, data)` | `SaveWorker` | validée **et** persistée | logué en warning, absorbé |

`on_save` traverse `PhaseStorage` → `SaveItem`, dont le callback change de
signature : `(SaveItem) -> None` devient `(chunk, data) -> None`.

Migration : un hook d'export ou de revue va dans `on_save` ; un effet de bord que
le chunk suivant doit voir reste dans `after_response`.

`after_response` est désormais appelé **aussi sur le chemin cache** : un run
entièrement en cache déclenche les mêmes hooks qu'un run complet.

#### 2. Le worker de validation est choisi par phase

`ValidationWorkerPool` sélectionne la classe de worker sur `phase.content_checks`
au lieu d'instancier `UnifiedValidationWorker` pour tout le monde :

| `content_checks` | Worker | Donnée attendue |
|------------------|--------|-----------------|
| non vide | `UnifiedValidationWorker` | mapping line-indexed |
| vide | `SchemaOnlyValidationWorker` (nouveau) | quelconque — jamais inspectée |

`UnifiedValidationWorker` copiait `item.data` dans un `LineIndexed` pour toutes
les phases ; sur une `list[LLMTermeGlossary]` ou un `AnalyseChapter`, cette copie
produisait une structure aplatie. Le socle commun est extrait dans
`validation/worker_base.py` (`ValidationWorker`, `RejectOutcome` — ex
`_RejectOutcome`).

`switch_phase()` recycle les workers quand la phase suivante demande l'autre
classe. Le `SaveWorker` n'est jamais interrompu : il draine encore la queue de la
phase précédente.

#### 3. Le glossaire source n'est plus écrasé

Le pipeline écrivait le glossaire enrichi dans `<epub_dir>/.<stem>_glossary.json`,
c'est-à-dire dans le fichier même passé à `run(glossary=…)` — corrections
manuelles comprises. `Pipeline._glossary_export_path()` bascule sur
`.<stem>_glossary.generated.json` quand le nom d'export désigne la source.
Sans glossaire source fourni, le nom par défaut est inchangé.

### ✨ Nouveautés

#### Audit d'une phase contre son cahier des charges

Nouveau package `ebook_translator.audit` et commande
`python -m ebook_translator.audit <cache_dir> --phase glossary`. Là où
`ebook_translator.bench` compare N variantes entre elles, l'audit confronte **une**
sortie de phase à ce qu'elle devait être — deux variantes également mauvaises se
départagent quand même sur un banc comparatif.

L'audit ne lit que le disque : n'importe quel cache de pipeline
(`.<stem>_cache/` ou `bench/runs/<id>/work/<v>/cache/`), aucun appel LLM, rejouable
sans coût. Il écrit `audit/runs/<horodatage>-<phase>/` avec le rapport, les
métriques, le cahier des charges recopié et un manifeste ; `/phase-audit` délègue
ensuite l'instruction à l'agent `phase-auditor`.

**Aucun seuil GO/NO-GO n'est appliqué** : « 48 termes » n'est ni bon ni mauvais dans
l'absolu, cela dépend du livre. La référence est en prose
(`audit/specs/<phase>.md`), les chiffres décrivent, l'agent juge. Corollaire assumé :
les catégories heuristiques portent des faux positifs, que l'agent doit trier.

Un seul auditeur pour l'instant, la phase glossaire, sur un socle générique
(`PhaseAuditor`, `AuditFindings`, `AuditSource`). Sept catégories d'écart :
`nom-commun-article`, `sans-marque-nom-propre`, `ancrage-faible`, `redondance`,
`traduction-instable`, `classement-instable`, `candidat-manque`. Sur *The Yellow
Wallpaper* : 48 termes uniques pour 6219 mots, dont **41 (85 %) touchés par au moins
une observation**, et 28 termes à article de tête sans marque de nom propre.

Trois garde-fous, tirés du premier audit réel :

- une catégorie **mesurée sans cas** reste au rapport avec un effectif de `0` — la
  faire disparaître la rendait indiscernable d'une catégorie non mesurable, listée
  elle en « Limites de mesure » ;
- les catégories n'étant **pas disjointes**, la somme de leurs effectifs (78) dépasse
  le nombre de termes (48) : la métrique « Termes touchés par au moins une
  observation » donne l'ampleur réelle, et chaque catégorie nomme ses cas au-delà des
  12 exemples détaillés ;
- `redondance` ne compte plus **que** les réémissions postérieures à la convergence.
  Réémettre un terme non stabilisé est le mécanisme d'accumulation de poids, et
  `glossary_existing_block.jinja` le réclame explicitement. Les seuils viennent de
  `glossary.converged_weight()` (5 émissions unanimes) et
  `DEFAULT_MIN_REINJECTION_WEIGHT` (3), pas d'une constante recopiée. Un livre de
  moins de 5 chunks ne fait converger aucun terme : le rapport le signale, et la
  stabilisation n'y est simplement pas mesurable.

Voir [AUDIT.md](AUDIT.md).

### 🔧 Modifications

- `Mode.TOOLS_STRICT` → `Mode.JSON` pour la voie Instructor : `TOOLS_STRICT`
  n'applique pas les contraintes de structure chez DeepSeek et produisait des
  JSON invalides. La validité du contenu reste portée par Pydantic.
- `max_retries` propagé jusqu'à `instructor.create_with_completion()` :
  l'erreur de validation Pydantic est réinjectée dans la conversation pour que
  le modèle se corrige.
- `LLM(prompt_dir=…)` et `LLMBuilder` prennent par défaut
  `DEFAULT_PROMPT_DIR`, résolu depuis le package `template` installé. L'ancien
  `"template"` relatif ne fonctionnait que lancé depuis la racine du dépôt.
- Logs : `exc_info` sur les `logger.error` des chemins LLM et cache ; le format
  par défaut porte `fichier:ligne (fonction)`.
- Phase 0 : les fiches Markdown sont nommées `<outer_key>-<inner_key>.md`, un
  bloc n'écrase plus le précédent au sein d'un chapitre.

### 🐛 Corrections

- `Pipeline.clear_caches()` supprimait `<cache_dir>/glossary.json`, chemin que
  rien n'écrit — le nettoyage du glossaire ne faisait rien. Il vise les noms
  d'export réels, en épargnant la source.
- `Pipeline.glossary` n'existait qu'après `run()` : `clear_caches()` appelé
  avant levait `AttributeError`.
- `ValidationWorkerPool` réarmait l'événement d'arrêt après le `join`. Un worker
  dépassant le délai — plausible pendant un appel LLM de correction — repartait
  consommer la queue avec l'ancienne phase. Chaque génération de workers a
  désormais son propre événement.

### 📊 Compteurs

`pytest` **790 passés** · `basedpyright src/` **0 erreur** · couverture **83,72 %**
(seuil de 80 % désormais tenu — l'entrée de dette correspondante est soldée).

### ⚠️ Effets de bord

Deux conséquences assumées, détaillées dans
[TECHNICAL_DEBT.md](TECHNICAL_DEBT.md) :

- **Glossaire peuplé depuis un hook asynchrone** — `GlossaryPhase` a migré
  `_populate_glossary()` dans `on_save`. Le peuplement n'est plus garanti
  visible du chunk suivant, et une exception y est absorbée par le `SaveWorker`
  (entrée « Le glossaire est peuplé depuis un hook asynchrone »).
- **`LLM.max_retries` pilote deux mécanismes** — la boucle de retry réseau de
  `query()` et les corrections de schéma d'instructor dans `json_query()`
  partagent le même réglage (entrée « `LLM.max_retries` pilote deux mécanismes
  différents »).

---

## Version 0.12.0 - Pivot TypedDict et validation unifiée (2026-07-30)

### 🎯 Vue d'ensemble

Refonte de trois couches — types, persistance, validation — menée sur huit mois,
suivie d'une remise en état du dépôt (`repo-cleanup`) et d'un réalignement complet
de la documentation (`docs-realignment`).

Le fil directeur : **une source de vérité par artefact**. Le format de sortie LLM
n'est décrit qu'à un endroit, le schéma JSON qu'à un endroit, le mapping erreur →
correction qu'à un endroit.

### ⚡ Breaking Changes

#### 1. Deux paramètres de type traversent le pipeline

- **`M` (payload)** — modèle Pydantic validant la *forme* de la sortie LLM
- **`DT` (data)** — vue `TypedDict` circulant en queue et en cache

`M.build()` produit `DT`. La conversion n'étant pas réversible, l'instance
Pydantic est abandonnée dès l'executor : plus de `dict[int, str]` anonyme
voyageant à travers le pipeline.

#### 2. `ContexteTraduction` remplacé par `AnalyseChapter`

Phase 0 produit désormais une fiche **stratifiée**, validée par Instructor
(`Mode.TOOLS_STRICT`) sur son schéma Pydantic :

```python
from template.phase.analyze_chapter_layered_models import AnalyseChapter
# noyau_stable      : invariants du livre (genre, registre, style, tonalité, pistes)
# couche_narrative  : état du récit (résumé, arcs, tensions, thèmes, références)
```

L'analyse est **incrémentale** : chaque bloc reprend et enrichit la fiche du bloc
précédent, selon trois modes (`bootstrap`, `seed`, `incremental`).

**Le cache Phase 0 est invalidé** — le format de stockage a changé.

Phase 0 ne peuple plus le glossaire : c'est le rôle de `GlossaryPhase`.

#### 3. La transition glossaire devient une phase

`transition/` est supprimé. `GlossaryPhase` est une phase à part entière,
sélectionnable via `PhasesBuilder().add_glossary_generation()`.

#### 4. `ValidationPipeline` remplacé par `UnifiedValidationWorker`

Un **seul** worker sert toutes les phases ; aucune sous-classe par phase. Chaque
phase déclare ses `content_checks`, et le routage des corrections passe par
`RETRY_REGISTRY` (`ErreursType` → template, params, `build`, mode de fusion).

Le traitement est **check par check** : chaque check épuise son budget de retries
sur ses propres échecs avant de passer la main. Si un échec survit, ses
`relevant_indices` sont abandonnés et le chunk est **sauvegardé partiel** — un
chunk avec des trous vaut mieux qu'un chunk rejeté.

Supprimés : `checks/pipeline.py`, `checks/retry_helper.py`, `checks/check_tests/`,
`AnalysisChecks`, `GlossaryValidator`, `AnalysisValidator`, le package `validator/`.

#### 5. Persistance stratifiée en trois couches

| Couche | Rôle |
|---|---|
| `ByteStore` / `FileByteStore` | octets bruts, verrous par fichier, écriture atomique |
| `ChunkPersister` | décide *ce qui* est écrit — `LineIndexedPersister`, `MemoizedChunkPersister` |
| `PhaseStorage` | lie un persister, un store et un fallback |

#### 6. Source de vérité unique pour le format `<N/>…[=[END]=]`

`translation/parser.py` est supprimé. Le format est décrit et validé par le seul
`LineIndexedLLMResponse` (submodule `template`), via des `model_validator`
Pydantic.

#### 7. Templates réorganisés en paires

Chaque prompt devient une paire `<nom>_system.jinja` + `<nom>_user.jinja`,
répartie en `common/` / `phase/` / `retry/` et résolue par les enums
`PhaseTemplate` et `RetryTemplate`. `TemplateNames` est supprimé.
`template/` devient un submodule git.

#### 8. API publique : les builders

`PipelineBuilder` / `LLMBuilder` / `PhasesBuilder` remplacent l'instanciation
manuelle. Le modèle, le mode thinking et la température appartiennent au
**client** :

```python
LLMBuilder().default_client(Deepseek(DeepseekModels.FLASH, thinking=False))
```

`LLMBuilder.model()`, `.reasoning()`, `.url()`, `.temperature()` et `.api_key()`
sont supprimés — sans cible depuis que `base_url` est un attribut de classe du
provider et que le thinking est un drapeau de configuration.

### 🐛 Corrections

**Neuf bugs `src`** mis au jour en remettant la suite de tests au vert, dont trois
qui empêchaient purement et simplement le pipeline de tourner (le pool construisait
ses workers avec des paramètres disparus, l'executor nommait mal un champ de
`ChunkContext`, `PhaseContext` était instancié sans son `name`). Un dixième à la
relecture : `Chapters` était construit sans store, donc les phases 1 et 2
traduisaient **sans contexte littéraire depuis toujours**.

**Quatre bugs supplémentaires dans les builders**, tous masqués à basedpyright par
un déballage `**kwargs` typé `dict[str, Any]` :

- `LLMBuilder.build()` passait `model_name` / `reasoning_name` / `url` /
  `temperature` à un `LLM` qui attend un `client`
- `add_glossary_generation(overlap_ratio=…)` transmettait la valeur sous le nom
  `overrides=`
- `add_*(llm_config=…)` visait un champ `llm_config` inexistant — les phases
  exposent `llm`
- `PipelineBuilder._bilingual_format` était une annotation nue, jamais affectée :
  tout `build()` sans appel à `.bilingual_format()` levait `AttributeError`

Trois bugs dans `Store` et deux dans `llm/` complètent le lot.

### 🧹 Nettoyage

- **-8274 lignes** au seul commit de remise en état, dont 2190 lignes de tests
  morts et 2937 lignes de la génération `checks` obsolète
- Paramètres morts retirés : `output_type`, `process_llm_response`,
  `PhaseBase.validate_payload`, `LLM.__init__(api_key=)`,
  `Pipeline.run(max_retries=)`
- `isort` retiré, remplacé par les règles `I` de ruff
- Documentation entièrement réalignée sur le code : `CLAUDE.md`, les deux README
  et `docs/`

### 📊 Compteurs

`pytest` **378 passés** · `basedpyright src/` **0 erreur** ·
`pre-commit run --all-files` vert.

### ⚠️ Écart connu

`ContentCheck.retry_strategy` et le helper `lookup_strategy()` décrivent une
politique de modèle par check (`NORMAL_ONLY`, `PROGRESSIVE_REASONING`,
`REASONING_ONLY`), mais le worker ne les consulte pas encore : le branchement est
marqué « déféré » dans le code. Ces métadonnées sont couvertes par les tests et
sans effet en production. Voir [VALIDATION.md](VALIDATION.md).
