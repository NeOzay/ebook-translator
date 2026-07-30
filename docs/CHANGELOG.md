# Historique des versions

> Ce fichier démarre à la version 0.12.0.
> Pour les versions 0.2.0 à 0.11.0 (2025-10-19 → 2025-11-15), voir
> [CHANGELOG_ARCHIVE.md](CHANGELOG_ARCHIVE.md) — les symboles qui y sont cités
> décrivent le code de l'époque et beaucoup n'existent plus.
> Pour les améliorations futures planifiées, voir [ROADMAP.md](ROADMAP.md).

## Récapitulatif des versions

| Version | Date | Fonctionnalité principale | Impact |
|---------|------|---------------------------|--------|
| **0.12.0** | **2026-07-30** | **Pivot TypedDict, persistance stratifiée, validation unifiée** | **-8274 lignes, 9 bugs corrigés** |

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
