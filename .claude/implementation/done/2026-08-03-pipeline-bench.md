---
slug: pipeline-bench
titre: Banc d'essais comparatif de pipelines
branche: pipeline-bench
base: master
statut: terminé
session: 2
plan: .claude/plans/eager-roaming-shannon.md
créé: 2026-08-02
maj: 2026-08-03 (session 2, rebase + run réel)
---

## Objectif et périmètre

**But** : un harness qui exécute N variantes de pipeline sur un même livre, isole leurs caches,
partage les phases figées pour la reproductibilité, et produit un corpus comparatif **anonymisé**
qu'un agent arbitre (Claude Opus, contexte propre) juge en aveugle.

**Critères de réussite** :

- `uv run python -m ebook_translator.bench bench/config_exemple.py` produit `bench/runs/<run_id>/`
  complet (métriques + corpus comparatif + manifeste).
- Une phase partagée entre variantes donne des sorties identiques sans appel LLM :
  `chunks_from_cache == chunks_total` et `llm_calls == 0`.
- `/bench-judge <run_id>` lance l'agent arbitre → `verdict.md` argumenté, levée d'anonymat en fin
  de fichier seulement.
- `uv run basedpyright src/` → 0 erreur ; `uv run pytest tests/bench --no-cov` au vert.

**Hors-périmètre** :

- Conversion tokens → euros (pas de table de prix par provider).
- Exécution concurrente de plusieurs variantes (séquentiel : durées incomparables sous contention API).
- Sous-échantillonnage de l'EPUB source (on choisit un petit livre).
- Modification des phases existantes ou de leur logique de cache.
- Intégration CI.

## Étapes

- [x] 1. `UsageMeter` + instrumentation — `llm/usage.py`, `llm/llm.py`, `pipeline/executor.py`,
      `pipeline/context.py`, `tests/llm/test_usage.py` (commit: 6bf5158)
- [x] 2. Modèle de configuration — `bench/suite.py` (`BenchSuite`, `Variant`, `Seed`, `RunEnv`)
- [x] 3. Isolation et amorçage — `bench/workspace.py` (symlink EPUB, copie des phases partagées)
- [x] 4. Exécution — `bench/worker.py` (enfant) + `bench/runner.py` + `bench/results.py`
- [x] 5. Collecte du corpus — `bench/collect.py` (traduction alignée, glossaire, analyse)
- [x] 6. Rendu — `bench/report.py` (`manifest.json`, `metrics.md`, `compare/`, `README.md`)
- [x] 7. CLI + exemple — `bench/__main__.py`, `bench/config_exemple.py`, `.gitignore`
- [x] 8. Arbitre — agent `.claude/agents/bench-judge.md` + skill `.claude/skills/bench-judge/SKILL.md`
- [x] 9. Documentation — `docs/BENCH.md`, renvois depuis `CLAUDE.md`
- [x] 10. Validation bout en bout sur un run réel — `bench/runs/20260803_210405`, corpus arbitré
      (`verdict.md`) ; défaut de collecte `_v2` trouvé et corrigé

## État courant

**Prochaine action** : run réel exécuté (`bench/runs/20260803_210405`, 2 variantes de température
sur *The Yellow Wallpaper*). Les critères observables sont vérifiés :

- `metrics.md` : `literary analysis (partagée)` → `chunks = cache = 3`, `appels LLM = 0` pour les
  deux variantes ;
- `compare/analysis.md` : les 3 fiches sont identiques d'une variante à l'autre ;
- `compare/translation/` : 60 fragments retenus sur 277, 2 rendus à l'identique.

`/bench-judge 20260803_210405` a rendu son `verdict.md` : classement argumenté, extraits à l'appui,
levée d'anonymat en fin de fichier. La chaîne complète est donc validée.

Deux défauts du harness sont apparus à cette occasion, non traités (voir notes) : le compteur de
chunks rejetés et l'échantillonnage du corpus. À arbitrer avant clôture.

**Vérification** : `uv run basedpyright src/` (0 erreur) et `uv run pytest --no-cov`
(92 tests `tests/bench`, 173 avec `tests/llm`)

**Notes** :

- Branche rebasée sur `master` = `39af5ff` (provider Mistral) le 2026-08-03, sans conflit malgré le
  recouvrement sur `llm/llm.py` et `pipeline/executor.py`. Sous-module `src/template` recalé sur
  `86f512b`.
- `tests/llm/test_client_base.py::TestApiKeyResolution::test_exits_when_no_key_is_available`
  échouait en local : `get_api_key` appelle `load_dotenv()`, qui restaurait `API_KEY` depuis le
  `.env` réel après le `monkeypatch.delenv`. Corrigé en neutralisant `load_dotenv` dans le test.
- **Défaut trouvé par le run réel** : `collect.read_translations` lisait la racine du dossier de
  phase, alors qu'un run écrit dans le sous-dossier `_v2` (`PhaseBase.BYTE_STORE_SUBDIR`) — corpus
  de traduction vide. Les deux emplacements sont désormais lus, le `_v2` primant. Le test passait
  parce que sa fixture écrivait elle aussi à la racine ; elle emploie maintenant le layout réel.
- Le pipeline laisse des trous : sur 276 fragments du chapitre, la variante A en produit 132 et la
  B 61, à cause de chunks rejetés en `output_format_invalid` (« Aucun segment `<N/>` reconnu »).
  Défaut côté pipeline, pas côté banc d'essais — le harness ne fait que le refléter.
- `metrics.md` affiche `Chunks rejetés = 0` alors que les logs montrent des rejets : le compteur
  ne capte pas les chunks sauvés partiels. À corriger si la robustesse doit être comparable.
- `CorpusOptions.max_fragments` retient les N **premiers** fragments du livre, pas un échantillon
  réparti. Sur ce run, la variante B n'avait rien produit dans cette zone : l'arbitre n'a vu aucune
  de ses traductions et l'a classée sur son seul glossaire. Un plafond qui échantillonne
  uniformément donnerait un corpus représentatif.
- Modifications antérieures mises de côté : `stash@{0}` sur le repo parent
  (`examples/example_pipeline.py`) et un stash dans le sous-module `src/template`
  (validator `_tronque_pistes` commenté). À reprendre hors de ce chantier.
- `uv run pytest` sans `--no-cov` sort en 1 à cause du seuil `--cov-fail-under=80` : lire le
  résumé, pas le code de sortie.

## Journal de décisions

- **2026-08-03** — L'audit d'une phase contre son cahier des charges part dans un chantier séparé
  (`bench-audit`), avec métriques déterministes d'abord et agent auditeur ensuite. *Pourquoi* : le
  banc compare des variantes entre elles, auditer une phase seule est un autre objet.
  *Rejeté* : étendre `pipeline-bench` (aplatissement final illisible).

- **2026-08-02** — Phases partagées **copiées** depuis un run d'amorçage, pas symlinkées.
  *Pourquoi* : une variante qui recalcule une partie de la phase corromprait la référence commune.
  *Rejeté* : symlink du répertoire de store (gain disque négligeable, risque d'écriture croisée).

- **2026-08-02** — Configuration = script Python exposant `suite: BenchSuite`, chargé par
  `importlib`. *Pourquoi* : garde toute l'expressivité des builders (clients, enums de modèles) que
  du TOML ne saurait porter. *Rejeté* : matrice déclarative YAML/TOML.

- **2026-08-02** — Jugement en aveugle : labels `A/B/C` par mélange déterministe seedé sur
  `run_id`, mapping isolé dans `manifest.json`. *Pourquoi* : empêche le biais pro-gros-modèle et
  l'ordre de déclaration comme indice. *Rejeté* : étiqueter chaque extrait avec ses paramètres.

- **2026-08-02** — Arbitre = agent dédié (`.claude/agents/bench-judge.md`) lancé par un skill.
  *Pourquoi* : contexte propre, l'aveugle est réel et le corpus volumineux ne pollue pas la session.
  *Rejeté* : arbitrage dans la conversation principale.

### Décisions antérieures

- Résultats de variante échangés par fichier JSON, pas par stdout — la sortie du fils reste libre
  pour les barres de progression et les logs du pipeline.
- `UsageMeter` dans `llm/usage.py` et actif par défaut — sinon `llm.py` importerait `bench`, ce qui
  inverserait les couches ; le coût est négligeable face au réseau.
- Un sous-processus par variante — `CommunContext` est un `FrozenStatic` gelé au premier `run()` et
  `HtmlPage` un singleton, deux runs dans le même processus sont impossibles.
