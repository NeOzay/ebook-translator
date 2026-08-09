---
slug: logs-par-run
titre: Logs par run de banc
branche: logs-par-run
base: master
statut: terminé
session: 2
plan: .claude/plans/resilient-gathering-otter.md
créé: 2026-08-04
maj: 2026-08-05
---

## Objectif et périmètre

**But** : chaque pipeline écrit ses logs dans son propre workspace de banc, au lieu du
`logs/run_<horodatage>/` global et sans rattachement au run. Premier des trois défauts de
la dette technique § 10.

**Critères de réussite** (mesurables) :
- `bench/runs/<run_id>/logs/` contient les logs du harness ;
- `bench/runs/<run_id>/work/<variante>/logs/` contient `translation.log` et les `llm_*.log`
  de cette variante ;
- un run de banc ne crée plus aucun `logs/run_*` ;
- `uv run pytest --no-cov` vert, `basedpyright src/` à 0 erreur.

**Hors-périmètre** :
- capture de `stdout`/`stderr` du sous-processus (volontairement non capturés pour les
  barres de progression) ;
- les deux autres défauts de la dette § 10 : `status: "ok"` qui ne vérifie rien, absence de
  plafond de débit par fournisseur ;
- exposition d'un `log_dir` sur `PipelineBuilder`.

## Étapes

- [x] 1. `LazyFileHandler.set_directory` — `src/ebook_translator/logger.py`
- [x] 2. Registre `_FILE_HANDLERS` + `LogSession.redirect` — `src/ebook_translator/logger.py`
- [x] 3. Le worker se redirige — `bench/workspace.py`, `bench/suite.py`, `bench/worker.py`
- [x] 4. Le harness se redirige — `bench/runner.py`
- [x] 5. ~~`.gitignore`~~ — SANS OBJET : `bench/runs/` est déjà ignoré (`.gitignore:79`)
- [x] 6. Tests — `tests/logger/test_redirect.py` (7), `test_workspace.py` (3), `test_worker.py` (1), `test_runner.py` (1) (commit: 7f115aa, étapes 1-6)
- [x] 7. Vérification : tests, typage, **et run réel** — run `20260805_182835` (commit: 605680c)

## État courant

**Toutes les étapes sont faites.** Le chantier est prêt pour la clôture (aplatissement de
`logs-par-run` sur `master`).

**Vérification finale** — run réel `bench/runs/20260805_182835` (session 2, 2026-08-05),
`bench/config_glossaire.py`, variantes `deepseek` et `mistral` :

- `<run_id>/logs/translation.log` — logs du harness ;
- `work/<variante>/logs/translation.log` + 4 `llm_glossary_chunk_*.log` par variante, tous
  non vides (~17 ko par échange LLM) ;
- `logs/` inchangé, dernier répertoire `run_20260804_220615` (veille) : aucun `run_*` neuf.

Les trois critères de réussite sont donc prouvés en conditions réelles, y compris la
production de `llm_*.log` que les tests unitaires ne pouvaient que simuler.

**Vérifications acquises en session 1** : `uv run pytest --no-cov` → 662 passed ·
`basedpyright src/` → 0 erreur · `pre-commit run --all-files` → tout vert.

**Notes** : le point dur était que `LazyFileHandler` diffère la création du fichier mais fige
le chemin dans `__init__`, donc à l'import — avant que le worker ait lu ses arguments. D'où
le registre et la redirection a posteriori. Le second canal (fichiers d'échange LLM) résout
son chemin à chaque requête via `get_session_log_path` et suit donc automatiquement — c'est
ce qui rapatrie les traces d'échec de débit sans une ligne de plomberie supplémentaire.

Une fixture autouse dans `tests/bench/conftest.py` restaure la session de logs après chaque
test : `run_suite` et `worker.main` re-ciblent les loggers du processus, et sans cela un test
enverrait les logs des suivants dans son `tmp_path` déjà effacé.

## Journal de décisions

### Décisions antérieures

- Redirection explicite (registre de handlers + `LogSession.redirect`) plutôt que variable
  d'environnement — une variable ne servirait que le banc, pas les appelants bibliothèque.
- Le chemin des logs d'une variante est dérivé de `--work-root` et `--variant` dans le
  worker, sans argument CLI supplémentaire — aucun risque de désynchronisation père/fils.
- Logs de variante dans `work/<variant>/logs/`, à côté du `cache/` — supprimer un workspace
  supprime ses logs.
- Aucune règle `.gitignore` ajoutée : `bench/runs/` y figure déjà en entier.
- `RunEnv.logs_dir` est une propriété dérivée de `workspace`, pas un champ — le dataclass est
  gelé et un champ requis de plus aurait cassé tous les appelants.
