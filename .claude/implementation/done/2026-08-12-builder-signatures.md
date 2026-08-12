---
slug: builder-signatures
titre: Signatures du builder miroir des phases (dette `_skip_none`)
branche: builder-signatures
base: master
statut: terminé
session: 1
plan: .claude/plans/lovely-splashing-dijkstra.md
brief: .claude/implementation/builder-signatures.brief.md
créé: 2026-08-12
maj: 2026-08-12
---

## Objectif et périmètre

Repris du brief.

**Symptôme** : `_skip_none(**overrides) -> dict[str, Any]` rend basedpyright aveugle aux arguments
inexistants. Le motif a déjà produit quatre bugs fatals à l'exécution (docs/TECHNICAL_DEBT.md n°2).

**But** : synchroniser automatiquement la signature de chaque `PhasesBuilder.add_*` sur le
`__init__` de la dataclass de phase, via un décorateur `_mirrors(PhaseCls)` (ParamSpec).

**Critères de réussite** :
- `uv run basedpyright src/` : 0 erreur, plus aucun `ignore[arg-type]` sur `run()`
- plus aucune occurrence de `_skip_none` dans `src/`
- un mauvais nom d'argument sur un `add_*` est signalé par basedpyright
- `uv run pytest` passe (gate 80 %)
- `head_tail_balance`, exposé par le miroir, est cadré par des tests

**Hors-périmètre** : aucun changement de comportement du pipeline · `LLMBuilder` non retouché ·
`bench/runs/*/config.py` intactes · incohérence `head_tail_balance` 0.75 (Segmentator) vs 0.5
(helper) constatée mais non corrigée.

**Signaux de dérive** :
- une couche d'abstraction qui apparaît autour des phases (wrapper/sous-builder) — c'est l'option
  écartée qui revient
- des defaults de phase recopiés dans le builder — objectif manqué

## Étapes

- [x] 1. `_mirrors` + `add()` générique, converti sur `add_initial_translation` seule — `pipeline/builder.py`
- [x] 2. Convertir les 3 autres `add_*` + docstrings référençant la phase
- [x] 3. Solder `PipelineBuilder.build()` : `Pipeline(...)` explicite, `RunArgs` TypedDict, suppression de `_skip_none` et des 2 `ignore`
- [x] 4. Tests : `test_builder.py` (`llm`, `RunArgs`, mauvais kwarg) + `test_helper.py` (`head_tail_balance`)
- [x] 5. Documentation : TECHNICAL_DEBT (dette retirée + renumérotation), ARCHITECTURE:51, CHANGELOG

## État courant

**Prochaine action** : aucune — chantier clos le 2026-08-12.
**Vérification** : `uv run pre-commit run --all-files` (passé) · `uv run pytest` → 801 passés ·
`grep -rn "_skip_none" src/` → vide · `uv run basedpyright examples/ bench/config_exemple.py` → 0.
**Notes** : la forme « docstring seule » a tenu — basedpyright ne bronche pas et le corps est
fourni par `_mirrors`. Le repli prévu (délégation explicite) n'a pas servi.

## Journal de décisions

- **2026-08-12** — Miroir de signature par `ParamSpec` plutôt qu'un sous-builder par phase — aucun
  default recopié, donc aucune dérive possible entre phase et builder.
- **2026-08-12** — Paramètre public renommé `llm_config` → `llm` — le nom colle au champ réellement
  alimenté ; renommer `PhaseBase.llm` aurait déplacé la rupture sur 7 usages internes.
- **2026-08-12** — `head_tail_balance` ouvert et cadré par des tests plutôt que fermé en
  `init=False` — le chevauchement est déjà en service, seul le réglage n'était jamais varié.
- **2026-08-12** — Pas de `functools.wraps` dans `_mirrors` — il pose `__wrapped__`, que
  `inspect.signature` suit jusqu'au stub, annonçant « aucun argument ».
- **2026-08-12** — Signature runtime non publiée — `inspect.signature(PhaseCls)` lève `NameError`,
  les annotations de `PhaseBase` n'étant pas résolvables à l'exécution (`PhaseContext` sous
  `TYPE_CHECKING`). Constat laissé au dépôt, hors périmètre.
