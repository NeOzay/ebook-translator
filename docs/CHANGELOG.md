# Historique des versions

> Ce fichier démarre à la version 0.12.0.
> Pour les versions 0.2.0 à 0.11.0 (2025-10-19 → 2025-11-15), voir
> [CHANGELOG_ARCHIVE.md](CHANGELOG_ARCHIVE.md) — les symboles qui y sont cités
> décrivent le code de l'époque et beaucoup n'existent plus.
> Pour les améliorations futures planifiées, voir [ROADMAP.md](ROADMAP.md).

## Récapitulatif des versions

| Version | Date | Fonctionnalité principale | Impact |
|---------|------|---------------------------|--------|
| *Non publié* | — | *Hooks de phase dédoublés, routage des workers par phase, glossaire source en lecture seule, sortie glossaire tabulaire* | *3 effets de bord, voir ci-dessous* |
| **0.12.0** | **2026-07-30** | **Pivot TypedDict, persistance stratifiée, validation unifiée** | **-8274 lignes, 9 bugs corrigés** |

---

## Non publié

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

`pytest` **385 passés** · `basedpyright src/ebook_translator` **0 erreur** ·
couverture 72,30 % (seuil 80 % non tenu, cf.
[TECHNICAL_DEBT.md](TECHNICAL_DEBT.md)).

### ⚠️ Effets de bord

Deux conséquences assumées, détaillées dans
[TECHNICAL_DEBT.md](TECHNICAL_DEBT.md) :

- **Glossaire peuplé depuis un hook asynchrone** — `GlossaryPhase` a migré
  `_populate_glossary()` dans `on_save`. Le peuplement n'est plus garanti
  visible du chunk suivant, et une exception y est absorbée par le `SaveWorker`
  (entrée 6).
- **`LLM.max_retries` pilote deux mécanismes** — la boucle de retry réseau de
  `query()` et les corrections de schéma d'instructor dans `json_query()`
  partagent le même réglage (entrée 7).

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
