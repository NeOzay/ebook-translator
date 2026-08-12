# Signatures du builder miroir des phases (dette `_skip_none`)

Brief : `.claude/implementation/builder-signatures.brief.md` (validé, 2026-08-12)

## Context

`_skip_none(**overrides) -> dict[str, Any]` ([builder.py:49](../../src/ebook_translator/pipeline/builder.py))
est déballé dans 7 appels. Un `dict[str, Any]` déballé rend basedpyright aveugle aux arguments
inexistants : le motif a déjà produit quatre bugs fatals à l'exécution, tous invisibles au
type-checker (docs/TECHNICAL_DEBT.md, dette n°2). Les tests de `test_builder.py` sont aujourd'hui
le seul filet.

On remplace l'indirection par un **miroir de signature** : chaque `PhasesBuilder.add_*` tire sa
signature du `__init__` de la dataclass de phase via `ParamSpec`. Aucun default n'est recopié —
c'est ce qui distingue cette solution d'un sous-builder par phase, écarté à l'évaluation.

Faisabilité vérifiée en sonde basedpyright avant planification : mauvais nom d'argument et mauvais
type détectés, champs `init=False` exclus automatiquement du miroir.

## Approche

```python
def _mirrors[**P](phase_cls: Callable[P, PhaseProtocol]) -> Callable[
    [Callable[..., "PhasesBuilder"]], Callable[Concatenate["PhasesBuilder", P], "PhasesBuilder"]
]:
    """Aligne la signature publique d'un `add_*` sur `phase_cls.__init__`."""
```

- `PhasesBuilder.add(phase_cls, *args: P.args, **kwargs: P.kwargs)` — méthode **publique**
  générique, chemin d'exécution réel et point d'extension pour une phase maison.
- Les 4 `add_*` deviennent des méthodes décorées dont le corps délègue à `add()`. Elles ne portent
  plus que leur docstring : c'est le décorateur qui expose la signature.
- Retour typé `PhasesBuilder` en dur, **pas `Self`** : `ParamSpec` ne compose pas avec `Self` dans
  un décorateur. `add_literary_analysis` renvoie déjà `PhasesBuilder` aujourd'hui.
- Le corps délègue à `add()` (publique) plutôt que de toucher `self._phases` depuis la closure du
  décorateur : `reportPrivateUsage = true` dans `pyproject.toml`.

Effet de bord assumé : le paramètre public devient `llm` (nom du champ) et non plus `llm_config`,
et `head_tail_balance` s'ouvre sur les 3 phases qui chevauchent — arbitrages tranchés au brief.

## Étapes

### 1. `_mirrors` + `add()` générique
`src/ebook_translator/pipeline/builder.py` — écrire le helper et la méthode publique, puis
convertir **une seule** phase (`add_initial_translation`) et lancer basedpyright. C'est le point
de risque technique : le valider avant de propager.

### 2. Convertir les 3 autres `add_*`
`add_literary_analysis`, `add_glossary_generation`, `add_refinement`. Docstrings réécrites : elles
référencent la phase ajoutée au lieu de recopier ses `Args:`, et portent un exemple listant les
options communes de `PhaseBase` (`max_tokens`, `overlap_ratio`, `head_tail_balance`, `llm`) —
compensation de la signature devenue invisible à la lecture du fichier.

### 3. Solder `PipelineBuilder.build()`
- `Pipeline(...)` appelé explicitement (builder.py:595) — `cache_dir=None` est déjà accepté, et
  `_num_validation_workers` vaut déjà 2, jamais `None`.
- `run_kwargs` devient un `TypedDict` `RunArgs` (`target_language`, `output_epub`,
  `bilingual_format`, `glossary`) ; `_bilingual_format` porte `BilingualFormat.SEPARATE_TAG`
  comme default plutôt que `None`.
- `build() -> tuple[Pipeline, RunArgs]`.
- Supprimer `_skip_none` du module, et les **deux** `pyright: ignore[reportArgumentType]` qu'il
  imposait : `builder.py:628` et `bench/worker.py:86` (même cause, seul autre consommateur de
  `build()`).

### 4. Tests
`tests/pipeline/test_builder.py` :
- `test_llm_config_is_accepted` / `test_llm_config_accepts_a_client` (:167, :183) → paramètre `llm`.
- `test_run_kwargs_match_pipeline_run_signature` (:256) : filet par introspection devenu redondant
  une fois `RunArgs` typé → le remplacer par une assertion sur les clés attendues de `RunArgs`
  (le typage couvre la conformité, le test garde la trace du contrat).
- **Nouveau** : un mauvais kwarg lève `TypeError` à l'exécution
  (`pytest.raises(TypeError)` sur `add_initial_translation(nawak=1)`) — épingle le miroir côté
  runtime, là où basedpyright couvre déjà le statique.

`tests/segmentation/test_helper.py` — cadrer `head_tail_balance`, aujourd'hui exercé par aucun
test (critère de réussite du brief). Cible : `turn_resource_to_chunks`, dont c'est le paramètre
réel (helper.py:66). Réutiliser `_make_items` et `make_TagKey_mock` déjà en place :
- bornes : `< 0` et `> 1` lèvent `ValueError` (helper.py:69)
- un balance élevé donne un head plus fourni qu'un balance bas, à `overlap_ratio` égal
- `0.0` / `1.0` : tout le budget de chevauchement va au tail / au head

Plus un test dans `test_builder.py` : `head_tail_balance` passé à un `add_*` atteint bien le champ
de la phase (le miroir vient de l'ouvrir).

### 5. Documentation
- `docs/TECHNICAL_DEBT.md` : dette n°2 retirée (soldée, pas allégée).
- `docs/ARCHITECTURE.md:51` : la liste des overrides des `add_*` mentionne `llm` et le miroir.
- `docs/CHANGELOG.md` : rupture d'API `llm_config` → `llm`.

## Vérification

```bash
uv run basedpyright src/          # 0 erreur, et plus aucun ignore sur run()
uv run pytest                     # gate coverage 80 %
grep -rn "_skip_none" src/        # doit ne rien renvoyer
uv run ruff format src/ tests/ && uv run ruff check --fix src/ tests/
```

Sonde de non-régression manuelle (le point de la dette) : ajouter temporairement
`PhasesBuilder().add_refinement(nawak=1)` dans un fichier de `src/`, vérifier que basedpyright
signale *« Aucun paramètre nommé nawak »*, puis retirer.

Bout en bout, sans appel LLM : `uv run pytest tests/pipeline tests/segmentation -v`.
`examples/example_pipeline.py` et `bench/config_exemple.py` n'utilisent que `max_tokens` /
`max_workers` — ils doivent continuer à type-checker sans modification.

## Points laissés ouverts

- Si `reportPrivateUsage` ou un `reportUnknown*` bloque la forme « docstring seule », replier sur
  le corps qui délègue explicitement (`return self.add(RefinementPhase, *args, **kwargs)`), au
  prix d'une mention supplémentaire de la classe de phase. Décidé à l'étape 1, sur le vrai code.
- `Segmentator` prend `head_tail_balance=0.75` par défaut quand `turn_resource_to_chunks` prend
  `0.5` (segmentator.py:61 vs helper.py:66). Incohérence constatée, **hors périmètre** : la
  corriger changerait le découpage. Les tests de l'étape 4 épinglent le comportement actuel.
