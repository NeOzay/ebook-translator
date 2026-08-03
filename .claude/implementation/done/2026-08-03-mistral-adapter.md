---
slug: mistral-adapter
titre: Adaptateur pour les modèles Mistral (SDK mistralai)
branche: mistral-adapter
base: master
statut: terminé
session: 2
plan: .claude/plans/memoized-soaring-gosling.md
créé: 2026-08-03
maj: 2026-08-03
---

## Objectif et périmètre

**But** : ajouter un provider LLM **Mistral** utilisant le package officiel `mistralai`
(et non l'endpoint OpenAI-compatible), modèle visé **Mistral Large** (`mistral-large-latest`,
alias de Mistral Large 3 / `mistral-large-2512`, 256k de contexte).

**Critères de réussite** :

- `PipelineBuilder().llm(LLMBuilder().default_client(Mistral(MistralModels.LARGE)))` fait tourner
  les 4 phases, Phase 0 comprise (sortie structurée via `instructor.from_mistral`).
- `uv run basedpyright src/` → 0 erreur.
- `uv run pytest --no-cov` → tous les tests passent, **sans modifier** `deepseek.py` ni
  `tests/pipeline/test_builder.py` (non-régression du chemin DeepSeek).
- Les erreurs réseau Mistral déclenchent le retry avec backoff dans `LLM.query`.

**Hors-périmètre** :

- Chemin asynchrone (`complete_async`, `from_mistral(use_async=True)`) — le pipeline est synchrone.
- Streaming (`chat.stream`) — non supporté par le socle actuel, quel que soit le provider.
- Multimodal (images, documents), embeddings, OCR, agents Mistral.
- Migration du chemin DeepSeek vers les exceptions internes (décidé en « ajout » seulement).
- Modèles Magistral / mode raisonnement Mistral.

## Étapes

- [x] 1. Dépendances — `mistralai>=2.8.0,<3.0.0` + bump `instructor>=1.15.4` (obligatoire :
      jusqu'en 1.15.3 `instructor.providers` importait `from_mistral` de façon eager, ce qui
      cassait `import instructor` dès que `mistralai` 2.x était présent). Non-régression
      vérifiée : 412 passed, basedpyright 0 erreur.
- [x] 2. Socle agnostique extrait — `clients/protocol.py` (le contrat, isolé pour couper le
      cycle d'import) + `clients/base.py` (`LLMClientBase`) ; `client.py` réduite à
      `OpenAIClientBase(LLMClientBase)`. `deepseek.py` non modifié.
- [x] 3. Exceptions internes — `llm/errors.py` + clauses élargies dans `llm.py`
      (`(APITimeoutError, LLMTimeoutError)`, etc., aucune clause retirée).
- [x] 4. Le client — `clients/mistral.py` : `MistralModels` (small/medium/large), `Mistral`,
      TypedDicts, `parse()` (contenu en liste de chunks, `cached_tokens` via `model_extra`),
      `json_request` par `chat.complete` + `response_format_from_pydantic_model` avec boucle
      de reask, `prompt_cache_key` dérivée du prompt système, `_translate_error`.
- [x] 5. Exports + exemple + documentation — `llm/__init__.py`,
      `examples/example_pipeline_mistral.py`, `.env.example`, `README.md`, `README.fr.md`,
      `CLAUDE.md`, `docs/ARCHITECTURE.md`.
- [x] 6. Tests — `tests/llm/test_mistral_client.py` (26), `test_error_mapping.py` (11),
      `test_client_base.py` (17).

## Résultat face aux critères

| Critère | Statut |
|---|---|
| Les 4 phases tournent avec `Mistral(MistralModels.LARGE)` | **Partiel** — Phases 0, glossaire et 1 : 6/6 chunks, 0 rejeté. Phase 2 non validable (dette §8, voir ci-dessous) |
| Phase 0 en sortie structurée | ✅ — mais **pas** via `instructor.from_mistral` (incompatible `mistralai` 2.x) : `chat.complete` + `response_format_from_pydantic_model` |
| `basedpyright src/` → 0 erreur | ✅ |
| `pytest --no-cov` vert, sans toucher `deepseek.py` ni `test_builder.py` | ✅ — 466 passed |
| Erreurs réseau Mistral → retry avec backoff | ✅ — `llm/errors.py` ajouté aux clauses de `LLM.query` |

## État final

**Validation bout en bout (2026-08-03)** : Phases 0 / glossaire / initial → **6/6 chunks,
0 rejeté**, EPUB produit, aucune erreur. Le provider Mistral est fonctionnel.

**Phase 2 non validée** — et non validable en l'état : elle ne s'exécute jamais, quel que
soit le provider (`is_chunk_cached` consulte le fallback Phase 1 → tout chunk est vu comme
déjà en cache). Vérifié : cache `refinement/` supprimé → 27 cache hits, 0 appel, et le cache
reconstruit est identique à 266/266 lignes à celui de Phase 1. Documenté en
`docs/TECHNICAL_DEBT.md` §8, correctif renvoyé à un chantier dédié (touche la persistance,
pas le provider). `.add_refinement()` laissé commenté dans l'exemple, avec renvoi à la dette.

**Correctifs hors périmètre (2026-08-03)** — deux bugs du socle, révélés par le premier vrai
run bout en bout, sans lien avec Mistral :

1. `PhaseBase.get_chunks` (base.py:257) renvoyait le générateur de
   `Segmentator.get_all_segments()` sous un `cast(list[...])` mensonger → `len(chunks)` explosait
   dans l'executor dès la Phase 1 (Phases 0 et glossaire surchargent `get_chunks`, d'où leur
   passage). Introduit en `cad9828`. Corrigé par matérialisation en liste, plus un `list()`
   défensif dans `executor.py:73` (le `isinstance` en amont consommait le générateur avant le `len`).
2. `UnifiedValidationWorker._run_one_retry` (unified_worker.py:243) parsait la sortie de retry
   avec `model_validate_json`, alors que le format est du texte tagué `<N/>… [=[END]=]` — le
   parsing vit dans un validateur `mode="before"`, comme le fait déjà l'executor avec
   `model_validate`. Tout retry mourait en `json_invalid`, type absent d'`ErreursType`, ce qui
   tuait le thread worker. Le `_FakePayload` des tests n'acceptait que du JSON : il validait un
   chemin que la production n'emprunte jamais — aligné sur le format réel.

**Restes connus, non traités** (à arbitrer hors de ce chantier) :

- Un échec de schéma à l'executor (`executor.py:202`) perd le chunk sans retry ; seul le chemin
  worker a un budget de tentatives. C'est ce qui a fait disparaître les chunks 3 et 4.
  Documenté en `docs/TECHNICAL_DEBT.md` §9, avec le tout-ou-rien de `render_refine` (une ligne
  abandonnée en Phase 1 fait perdre un chunk entier en Phase 2).
- `PhaseStats.chunks_validated` jamais incrémenté → `Validés: 0` toujours affiché
  (`docs/TECHNICAL_DEBT.md` §10, points mineurs).

**Correctif templates (sous-module `src/template`, 2026-08-03)** : le bloc « Format de sortie »
de `common_translate_rules.jinja`, `common_translate_rules_light.jinja` et
`common_correct_rules.jinja` donnait un exemple **littéral** `<N/>Texte traduit...`. DeepSeek
généralisait, Mistral recopiait la balise telle quelle → `output_format_invalid` reproductible
sur les chunks 3 et 4. Exemples passés à des indices concrets (`<12/>`, `<13/>`) + interdiction
explicite d'écrire `<N/>`. Commité dans le sous-module (`86f512b`), pointeur bumpé côté parent.
**Le sous-module n'est pas poussé** : `86f512b` doit partir sur `origin` du dépôt
`ebook-translator-template`, sinon le pointeur du parent est irrésoluble pour les autres clones.

**Résultats** : `466 passed` · `basedpyright src/` 0 erreur · `pre-commit run --all-files`
tout vert. Couverture des nouveaux modules : `mistral.py` 96 %, `base.py` 94 %,
`protocol.py` et `errors.py` 100 %. Total du projet 72 % → 75 % (gate à 80 % toujours
non atteinte, comme documenté dans CLAUDE.md).

**Vérification** : `uv run basedpyright src/` && `uv run pytest --no-cov`

**Notes** :

- Le contrat à remplir est `ClientProviderProtocol` ([client.py:70](../../src/ebook_translator/llm/clients/client.py)) ;
  `@runtime_checkable` est load-bearing (`LLM.query` fait `isinstance` pour distinguer config et
  client de substitution) — ne pas y toucher.
- `LLMConfigExport.get_properties` compare le provider par **égalité stricte de classe**
  (llm_config.py:70) : passer exactement `cls` à `LLMConfigExport(...)`.
- `builder.py` ne connaît aucun provider : rien à y modifier.
- `instructor` est **inutilisable avec `mistralai` 2.x** (`from_mistral` fait
  `from mistralai import Mistral`, chemin déplacé vers `mistralai.client` en 2.0). Le provider
  Mistral n'y touche donc pas : `json_request` passe par `chat.complete` +
  `response_format_from_pydantic_model` (`mistralai.extra`), avec sa propre boucle de reask.
  `chat.parse` est écarté : il lève sans exposer le contenu brut, dont on a besoin pour la
  réinjection de correction et pour le log.
- **Fragilité préexistante** (hors périmètre) : `tests/llm/test_llm_logging.py::test_llm_creates_log_without_context`
  échoue sous `pytest-randomly` — il prend le `llm_*.log` le plus récent par `mtime` dans un
  répertoire de session partagé. Passe avec `-p no:randomly`.

## Journal de décisions

- **2026-08-03** — Le bug « Phase 2 inerte » (fallback dans `is_chunk_cached`) part en chantier
  séparé. *Pourquoi* : il touche la persistance, pas le provider, et son correctif rend la Phase 2
  réellement coûteuse en appels LLM — décision qui mérite son propre périmètre.
  *Rejeté* : le corriger ici (déborde largement d'un chantier « ajout de provider »).
- **2026-08-03** — Les trois bugs du socle rencontrés en validation (générateur `get_chunks`,
  parse JSON du retry, `<N/>` littéral) sont corrigés **dans** ce chantier. *Pourquoi* : chacun
  bloquait la validation bout en bout du provider, donc le critère de réussite lui-même.
  *Rejeté* : les renvoyer en dette (le chantier n'aurait été validé par aucun run réel).
- **2026-08-03** — `use_thinking` ignoré côté Mistral. *Pourquoi* : Mistral Large 3 n'expose pas de
  `reasoning_effort` documenté. *Rejeté* : mapper sur `prompt_mode="reasoning"` (risque de 400).
- **2026-08-03** — Le provider Mistral n'utilise pas instructor : `json_request` passe par
  `chat.complete` + `response_format_from_pydantic_model` avec sa propre boucle de reask.
  *Pourquoi* : `from_mistral` résout sa classe cliente via `from mistralai import Mistral`,
  chemin supprimé en 2.0 ; rester en 1.x aurait coûté `prompt_cache_key`, donc le prompt caching
  (tokens réutilisés à 10 % du prix d'entrée, très rentable ici — même prompt système sur des
  centaines de chunks). *Rejeté* : construire l'`Instructor` via `instructor.v2.core.patch_v2`
  (dépendance à des internes non publics).
- **2026-08-03** — `prompt_cache_key` dérivée par défaut de l'empreinte SHA-256 du prompt système
  (`_finalize_params`). *Pourquoi* : la clé n'est pas déduite du contenu par Mistral, et une clé
  par phase est exactement le grain utile. *Rejeté* : l'exiger de l'appelant (le caching serait
  resté inactif par défaut).

### Décisions antérieures

- Socle `LLMClientBase` agnostique extrait plutôt qu'une classe Mistral autonome — ~200 lignes
  de config et logging d'`OpenAIClientBase` étaient déjà agnostiques.
- Sortie structurée via `instructor.from_mistral(mode=MISTRAL_TOOLS)` — pour conserver le contrat
  `json_request`. **Révisée** en cours de chantier : `instructor` est inutilisable avec
  `mistralai` 2.x (cf. décision « n'utilise pas instructor » ci-dessus).
- Exceptions internes (`llm/errors.py`) **ajoutées** aux clauses d'openai dans `LLM.query`, pas
  substituées — sinon les erreurs Mistral tombent dans `except Exception`, sans backoff.
- `mistralai` en dépendance dure — aucun précédent d'`optional-dependencies` dans le repo.
