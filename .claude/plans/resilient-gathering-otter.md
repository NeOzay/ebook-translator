# Logs par run de banc

## Contexte

Un run de banc écrit aujourd'hui ses logs dans `logs/run_<horodatage>/`, relatif au
répertoire de travail, sans lien avec `bench/runs/<run_id>/`. Trois processus successifs
— le harness puis un sous-processus par variante — créent chacun leur propre répertoire
horodaté, et rien ne dit lequel appartient à quelle variante. Quand la variante Mistral du
run du 2026-08-04 s'est fait étrangler par le débit de l'API, la trace des requêtes en
échec existait bien sur le disque, mais dans un répertoire sans rattachement au run : le
rapport concluait `status: "ok"` et rien ne permettait de le contredire. C'est le premier
des trois défauts consignés en **dette technique § 10**.

**Résultat attendu** : chaque pipeline écrit ses logs dans son propre workspace, sous
`bench/runs/<run_id>/work/<variante>/logs/`, et le harness dans
`bench/runs/<run_id>/logs/`. Un run est alors auto-suffisant : cache, résultat, rapport et
trace au même endroit.

## Ce qui bloque aujourd'hui

`LogSession` ([logger.py:34](src/ebook_translator/logger.py#L34)) fige
`Path("logs") / f"run_{timestamp}"` au premier appel, sans aucun moyen de le configurer.
Le paramètre `log_dir` de `setup_logger` ([logger.py:161](src/ebook_translator/logger.py#L161))
existe mais n'est jamais passé : les ~30 modules font `get_logger(__name__)` au niveau
module.

Le vrai point dur est `LazyFileHandler` ([logger.py:103](src/ebook_translator/logger.py#L103)),
qui diffère la **création du fichier** mais pas la **résolution du chemin** : `self.filename`
est figé dans `__init__`, donc à l'**import**, avant que le worker ait lu ses arguments.

Deux choses jouent en notre faveur : chaque variante tourne dans son propre sous-processus
([runner.py:237](src/ebook_translator/bench/runner.py#L237)), donc un `LogSession` global
par processus est déjà la bonne granularité ; et le second canal, les fichiers d'échange
LLM, résout son chemin **à chaque requête** via `get_session_log_path`
([llm.py:225](src/ebook_translator/llm/llm.py#L225)) — il suivra donc automatiquement.

## Périmètre

**Dans le périmètre** : `src/ebook_translator/logger.py`,
`src/ebook_translator/bench/{worker,runner,workspace,suite}.py`, `.gitignore`, tests
associés, un run de vérification.

**Hors périmètre** :
- La **capture de `stdout`/`stderr` du sous-processus**. Elle reste volontairement non
  capturée ([runner.py:210](src/ebook_translator/bench/runner.py#L210)) pour que les barres
  de progression restent visibles. Ce chantier rapatrie ce qui passe par le *logger* ; un
  traceback écrit directement sur `stderr` continuera d'échapper au run.
- Les **deux autres défauts de la dette § 10** : `status: "ok"` qui ne vérifie rien, et
  l'absence de plafond de débit par fournisseur.
- L'exposition d'un `log_dir` sur `PipelineBuilder`. `LogSession.redirect()` suffit à
  l'appelant bibliothèque ; élargir l'API publique du builder est un choix distinct.

## Étape 1 — Rendre `LazyFileHandler` re-ciblable

`src/ebook_translator/logger.py`. Ajouter :

```python
def set_directory(self, directory: Path) -> None:
```

Ferme le `FileHandler` sous-jacent s'il a déjà été créé, remet `self._handler = None`, et
recalcule `self.filename = directory / self.filename.name`. Le nom de fichier
(`translation.log`, `custom.log`…) est conservé — seul le répertoire change.

Les rares records déjà écrits avant la redirection restent dans l'ancien fichier. C'est
accepté : entre l'import et l'appel à `redirect()` il ne se passe rien d'autre que du
chargement de modules.

## Étape 2 — Registre et `LogSession.redirect`

Même fichier. Un registre de niveau module, `_FILE_HANDLERS: list[LazyFileHandler]`,
alimenté par `setup_logger` au moment où il crée le handler. `setup_logger` sort tôt quand
`logger.handlers` est déjà peuplé — le handler est alors déjà au registre, il n'y a pas de
double inscription à craindre.

```python
@classmethod
def redirect(cls, directory: Path) -> None:
```

Fixe `_session_dir` et applique `set_directory` à tout le registre. Idempotent : deux
appels successifs avec le même chemin ne doivent rien casser.

`reset()` doit vider le registre, sans quoi les tests fuient les uns dans les autres.

## Étape 3 — Le worker se redirige

`src/ebook_translator/bench/workspace.py` : constante `LOGS_DIRNAME = "logs"` et fonction

```python
def variant_logs_dir(work_root: Path, variant_id: str) -> Path:
```

Le chemin est **dérivé**, pas transmis : le worker connaît déjà `--work-root` et
`--variant`, il n'y a pas de nouvel argument CLI à ajouter ni de risque de désynchronisation
entre le père et le fils. Ajouter aussi un champ `logs_dir` à `RunEnv`
([suite.py](src/ebook_translator/bench/suite.py)), renseigné par `prepare_workspace` :
une fabrique de variante peut en avoir besoin, et c'est rétrocompatible.

`src/ebook_translator/bench/worker.py` : appeler `LogSession.redirect(...)` **en tête de
`main()`**, avant `execute()`. Le répertoire n'a pas besoin d'exister —
`LazyFileHandler._ensure_handler` fait déjà son `mkdir(parents=True)`.

## Étape 4 — Le harness se redirige

`src/ebook_translator/bench/runner.py`, dans `run_suite`, juste après le calcul de `root` :
`LogSession.redirect(root / LOGS_DIRNAME)`.

Cela couvre du même coup `collect` et `report`, qui tournent dans le même processus après
`run_suite` ([bench/__main__.py:70](src/ebook_translator/bench/__main__.py#L70)) — leur
logger est lié à l'import, donc redirigé par le registre.

## Étape 5 — `.gitignore`

Ajouter `bench/runs/**/logs/`. Les fichiers d'échange LLM contiennent les prompts et les
réponses complètes, donc en pratique le texte intégral du livre. Le reste de
`bench/runs/` — rapports, `result.json` — continue d'être versionné.

## Étape 6 — Tests

`tests/logger/test_redirect.py` (nouveau) :
- redirection **avant** toute émission → le fichier naît au bon endroit ;
- redirection **après** émission → l'ancien fichier est fermé, la suite va dans le nouveau ;
- plusieurs loggers redirigés d'un seul appel ;
- idempotence ;
- `get_session_log_path` suit la redirection (c'est ce qui rapatrie les traces LLM).

`tests/bench/test_workspace.py` : `variant_logs_dir` tombe bien dans le workspace de la
variante, et `RunEnv.logs_dir` est cohérent avec elle.

`tests/bench/test_worker.py` : `main()` redirige avant d'exécuter.

Vérifier au passage que `tests/logger/test_logger_session.py` passe toujours — il assert
`session_dir.parent == Path("logs")` et l'égalité `file_handler.filename == session_dir /
"test_setup.log"`, deux invariants que ce chantier ne doit pas casser dans le cas non
redirigé.

## Étape 7 — Vérification

```bash
uv run pytest --no-cov
uv run basedpyright src/          # doit rendre 0 erreur
uv run pre-commit run --all-files
```

Puis un run réel, la seule preuve qui vaille — `bench/config_glossaire.py` est le plus
court (phase glossaire seule, deux variantes) :

```bash
uv run ebook-bench bench/config_glossaire.py
find bench/runs/<run_id> -name '*.log' | head -20
ls logs/                          # ne doit contenir aucun run_* nouveau
```

Attendu : `bench/runs/<run_id>/logs/` pour le harness,
`bench/runs/<run_id>/work/<variante>/logs/` contenant `translation.log` et les `llm_*.log`
de cette variante — et rien de neuf sous `logs/`.

## Suivi

Fichier de suivi `.claude/implementation/logs-par-run.md`, branche `logs-par-run` depuis
`master`. Arbre de travail propre, sous-module `src/template` non concerné.
