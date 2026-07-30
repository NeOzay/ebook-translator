---
slug: docs-realignment
titre: Réalignement de la documentation sur le code + balayage des restes
branche: docs-realignment
base: master
statut: terminé
session: 1
plan: .claude/plans/spicy-doodling-gizmo.md
créé: 2026-07-30
maj: 2026-07-30
---

## Objectif et périmètre

**But** : faire de `CLAUDE.md`, `README.md` et `docs/` un reflet vérifié du code. Le chantier
`repo-cleanup` (clos le 2026-07-30, commit `303ae36`, suivi dans
`done/2026-07-30-repo-cleanup.md`) a retiré des pans entiers du code en plaçant la doc
hors-périmètre. Balayer aussi les restes qu'il a laissés derrière lui.

**Critères de réussite** :
- Plus aucune référence à un symbole inexistant dans `CLAUDE.md`, `README.md` et `docs/`
  (hors `docs/CHANGELOG_ARCHIVE.md`, historique assumé)
- `uv run pytest` : 0 échec (baseline **351 passés**)
- `uv run basedpyright src/ examples/` : 0 erreur (baseline `src/` **0 erreur**)
- `uv run pre-commit run --all-files` : vert
- `LLMBuilder` construit un `LLM`, couvert par un test *(l'API retenue est
  `.default_client(client)` — voir journal)*

**Hors-périmètre** :
- Toute évolution fonctionnelle du pipeline (l'étape 1 est une réparation, pas une évolution)
- Toute refonte du submodule `template` — sa doc est lue, pas réécrite
- Réécriture des entrées de changelog ≤ 0.11.0 : déplacées, pas corrigées
- Décision sur le push vers `origin` (`origin/master` à `b6c8c04`, très en arrière) — à part
- `docs/ROADMAP.md` et `docs/SETUP.md` : 0 ref morte, non touchés

## Écart constaté (vérifié dans `src/`)

| La doc décrit | La réalité du code |
|---|---|
| `ValidationPipeline` + `checks/pipeline.py` + `check_tests/` | `UnifiedValidationWorker` + `content_checks` par phase, protocole `ContentCheck`, impls dans `checks/content/` |
| `checks/retry_helper.py` | `RetryStrategy` + `llm/retry_registry.py` + `validation/worker_retry.py` |
| `Store` seul dépositaire du cache | `Store` subsiste (per-phase via `StoreManager`), mais l'I/O passe par `PhaseStorage` = `ChunkPersister` + `ByteStore`/`FileByteStore` |
| Phase 0 → `ContexteTraduction` + `AnalysisValidator` (`analysis/`) | `AnalyseChapter` stratifié via Instructor ; `analysis/` n'existe plus, export dans `exporter/` |
| « Transition GlossaryValidation » (`transition/`) | `GlossaryPhase` — une phase à part entière ; `transition/` n'existe plus |
| `<N/>…[=[END]=]` parsé par `translation/parser.py` | source de vérité unique `LineIndexedLLMResponse` (submodule) |
| templates plats (`translate_base.jinja`) | paires `*_system` / `*_user` en `common/`, `phase/`, `retry/` |
| entry point `src/ebook_translator/__main__.py` | **le fichier n'existe pas** |
| *(absent de la doc)* | `PipelineBuilder` / `LLMBuilder` / `PhasesBuilder` — l'API publique |

## Étapes

- [x] 1. Builders réparés — **4 bugs**, pas un seul (voir État courant) ; les deux exemples
      cassés réécrits ; `tests/pipeline/test_builder.py` : 23 tests neufs (commit: b0928ce)
- [x] 2. `docs/ARCHITECTURE.md` réécrit — sections neuves « API publique » (builders) et
      « Persistance » (ByteStore / ChunkPersister / PhaseStorage) ; section Parser supprimée
- [x] 3. `docs/VALIDATION.md` et `docs/TEMPLATES.md` réécrits
- [x] 4. `docs/LITERARY_ANALYSIS.md` réécrit — schéma `AnalyseChapter` stratifié, 3 modes
      (bootstrap / seed / incremental) — étapes 2-4 (commit: 0935ab8)
- [x] 5. `CLAUDE.md`, `README.md` **et `README.fr.md`** réécrits — ce dernier n'était pas au
      repérage initial mais portait 7 refs mortes ; le laisser aurait fait diverger les deux
      README
- [x] 6. `docs/CODING_STANDARDS.md` — 5 exemples rebasés sur le code vivant
- [x] 7. `docs/REFACTOR_PHASEBASE.md` archivé en `done/2026-07-30-refactor-phasebase.md`,
      contenu intact sous un entête recensant **4 écarts** entre la cible décrite et le code
- [x] 8. Changelog archivé (`CHANGELOG_ARCHIVE.md`, contenu intact) + `CHANGELOG.md` neuf
      avec la seule entrée 0.12.0 ; liens entrants mis à jour dans `CLAUDE.md`, les deux
      README et `ROADMAP.md`. **`isort` corrigé au passage** : plus installé, la commande
      de `CLAUDE.md` échouait (aussi dans `CODING_STANDARDS.md` et `SETUP.md`)
- [x] 9. Restes balayés : `validator/` et `tests/transition/` (n'existaient plus que par leur
      `__pycache__`), `tests/checks/check_tests/`, `poetry.lock` + sa ligne `.gitignore` ;
      `tests/analysis/` → `tests/exporter/` ; `examples/test.py` → `example_epub_titles.py`
      normalisé ; 5 docstrings mortes corrigées. **Aucun symbole mort dans `src/`**
- [x] 10. Vérification finale : 7 contrôles passés. **Trouvaille** : `uv run pytest` sort en
      code 1 sur le seuil `--cov-fail-under=80` (couverture 71,90 %), tests tous verts —
      préexistant (68,45 % au départ), désormais documenté

## État courant

**Terminé.** Les 10 étapes sont cochées. Prêt pour la clôture (aplatissement sur `master`).

**Vérification** : `uv run pytest --no-cov -q` puis `uv run basedpyright src/ examples/`

**Compteurs de clôture** : `pytest` **378 passés / 0 échoué** (351 au départ + 27 neufs) ;
`basedpyright src/` **0 erreur**, `examples/` **0 erreur** ;
`pre-commit run --all-files` vert ; couverture **71,90 %** (68,45 % au départ).

**Grep de contrôle** : aucune référence à un symbole inexistant dans `CLAUDE.md`,
`README.md`, `README.fr.md` et `docs/`, hors les deux changelogs — l'archive assume ses
mentions historiques, et l'entrée 0.12.0 nomme légitimement ce qu'elle annonce supprimé.


**Dettes laissées, explicitement** :
- Couverture **71,90 %** contre un seuil `--cov-fail-under=80` : `uv run pytest` sort en
  code 1 tous tests verts. Préexistant (68,45 % au départ). `--no-cov` documenté ; remonter
  la couverture ou ajuster le seuil est une décision de fond.
- `ContentCheck.retry_strategy` + `lookup_strategy()` : testés, jamais appelés en production
  (branchement « déféré » dans le worker). Soit brancher la politique, soit retirer le
  mécanisme. Documenté comme écart connu dans `VALIDATION.md`.
- `literary_context_layered_block.jinja` (77 lignes, aucun référent) — submodule `template`,
  hors-périmètre.
- Rien n'a été poussé vers `origin` : `origin/master` reste à `b6c8c04`.

## Journal de décisions

Chantier clos ; entrées condensées à une ligne.

- `LLMBuilder` prend un client déjà construit (`.default_client(...)`) ; `.model()`,
  `.reasoning()`, `.url()`, `.temperature()`, `.api_key()` retirés — `base_url` est un
  attribut de classe du client, le thinking un flag de config, et chaque provider a sa
  propre enum de modèles.
- `ClientProviderProtocol[Any, Any]` sur `LLM.client` et sur les `llm_config` de phase — `U`
  est contravariant, la forme non paramétrée rejette tout client concret.
- Le bug `LLMBuilder` est réparé dans ce chantier plutôt que consigné en dette — documenter
  une API publique qui lève `TypeError` n'aurait aucun sens.
- Paramètres morts retirés (`LLM(api_key=)`, `Pipeline.run(max_retries=)`) plutôt que
  conservés en points d'extension — non lus, donc pièges.
- `docs/CHANGELOG.md` archivé tel quel, nouveau changelog démarrant à 0.12.0 — un changelog
  ne se réécrit pas, et l'historique reste consultable sans polluer le document courant.
- `docs/REFACTOR_PHASEBASE.md` archivé vers `done/` — doc de chantier, pas de référence.
- Les écarts constatés sont documentés comme tels plutôt que corrigés en silence ou passés
  sous silence : une doc qui décrit une politique inactive vaut moins qu'une doc qui le dit.

### Enseignement du chantier

Le déballage `**kwargs` typé `dict[str, Any]` a produit **quatre bugs** dans la seule API
publique du projet, tous invisibles à basedpyright et tous fatals à l'exécution. Aucun test
ne couvrait les builders. La leçon vaut au-delà : un `_skip_none(**overrides)` qui semble
DRY achète trois lignes en échange de la vérification statique de l'appel entier.

Corollaire pour un chantier de documentation : **vérifier chaque affirmation contre le code
avant de la réécrire**. Les README annonçaient une classe `EpubTranslator` qui n'a jamais
existé sous cette forme, un `start.py` absent, Poetry et Python 3.12 là où le projet exige
uv et Python 3.14, et trois variables d'environnement dont aucune n'est lue. Renommer les
symboles obsolètes n'aurait rien réglé.
