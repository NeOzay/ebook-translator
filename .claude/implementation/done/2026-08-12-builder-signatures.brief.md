---
slug: builder-signatures
titre: Signatures du builder miroir des phases (dette `_skip_none`)
statut: validé
créé: 2026-08-12
---

## Intention

**Symptôme** : `_skip_none(**overrides) -> dict[str, Any]` rend basedpyright aveugle aux
arguments inexistants. Le motif a déjà produit quatre bugs fatals à l'exécution, invisibles au
type-checker (dépôt: docs/TECHNICAL_DEBT.md#L62-84).
**But** : « `_skip_none` masque la signature des phases » — synchroniser automatiquement la
signature de chaque `PhasesBuilder.add_*` sur le `__init__` de la dataclass de phase, via un
décorateur `_mirrors(PhaseCls)` (ParamSpec/Concatenate). Variante B, retenue après évaluation
comparée (dit).

## Critères de réussite

- `uv run basedpyright src/` : 0 erreur, et le `# type: ignore[arg-type]` de
  `PipelineBuilder.run` a disparu (dépôt: src/ebook_translator/pipeline/builder.py:628)
- plus aucune occurrence de `_skip_none` dans `src/` (7 aujourd'hui)
- un mauvais nom d'argument sur un `add_*` est signalé par basedpyright — vérifié en sonde sur
  `add_initial_translation(nawak=1)` → *« Aucun paramètre nommé nawak »*
- `uv run pytest` passe (gate coverage 80 %)
- `head_tail_balance`, exposé par le miroir et jamais testé aujourd'hui, est cadré par des
  tests (dit)

## Hors-périmètre

- pas de changement de comportement du pipeline : refonte de typage uniquement
- `LLMBuilder` n'est pas retouché — ses defaults recopiés à la main restent tels quels
- `bench/runs/*/config.py` : archives de runs passés, non touchées

## Signaux de dérive

- si une couche d'abstraction apparaît autour des phases (wrapper/sous-builder par phase), c'est
  raté — c'est précisément l'option écartée (dit)
- si les defaults des phases se retrouvent recopiés dans le builder, l'objectif est manqué

## Contraintes connues de l'utilisateur

- **Visibilité des champs** : se contrôle via `field(init=False)` côté phase, pas côté builder (dit).
  Critère : un champ est fermé quand son comportement n'est pas testé et jugé risqué — c'est
  pourquoi `LiteraryAnalysisPhase.overlap_ratio` est `init=False` (dit)
- **`head_tail_balance` reste ouvert** sur les 3 phases qui chevauchent, et on le cadre par des
  tests plutôt que de le fermer (dit). Aucun test ne l'exerce aujourd'hui (dépôt: `grep` tests/ vide)
- **Docstrings** : les `add_*` référencent la phase qu'elles ajoutent au lieu de recopier ses
  `Args:` (dit)
- **Découvrabilité** : la signature n'étant plus lisible dans `builder.py`, la docstring porte un
  exemple avec les options communes de `PhaseBase` — risque assumé (dit)
- **Faisabilité vérifiée** : sonde basedpyright — mauvais nom et mauvais type détectés, champs
  `init=False` exclus automatiquement (dépôt: sonde scratchpad, 2026-08-12)
- **Rupture limitée** : aucun usage de `llm_config=` hors tests et doc — `examples/` et `bench/`
  n'appellent les `add_*` qu'avec `max_tokens` / `max_workers`
  (dépôt: examples/example_pipeline.py:49, bench/config_exemple.py:68-70)

## Arbitrages rendus

- **Paramètre public renommé `llm_config` → `llm`** : miroir strict assumé. À mettre à jour :
  `tests/pipeline/test_builder.py:167,183` et `docs/ARCHITECTURE.md:51` (tranché 2026-08-12)
- **Les 2 sites de `PipelineBuilder.build()` sont dans le périmètre** : appel `Pipeline(...)`
  explicite et `run_kwargs` en `TypedDict`, pour faire tomber le `# type: ignore[arg-type]`.
  La dette n°2 est soldée en entier, pas allégée (tranché 2026-08-12)

## Incertitudes à lever en plan

- sort de `tests/pipeline/test_builder.py:256` (`test_run_kwargs_match_pipeline_run_signature`) :
  filet par introspection devenu redondant une fois `run_kwargs` typé — supprimer ou convertir
  en assertion de type ? À trancher dans le plan
- forme exacte du helper `_mirrors` : décorateur nu vs `Concatenate[PhasesBuilder, P]` explicite,
  et ce que devient le `Self` de retour (la sonde a dû figer `PhasesBuilder` en dur)
