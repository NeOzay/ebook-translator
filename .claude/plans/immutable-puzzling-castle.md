# bench-audit — audit d'une phase contre son cahier des charges

## Contexte

Le banc d'essais (`src/ebook_translator/bench/`) compare N variantes entre elles. Il ne
dit jamais si une phase fait *son* travail : deux variantes également mauvaises se
départagent quand même.

Le glossaire le montre. Sur *The Yellow Wallpaper* (run `bench/runs/20260803_210405`),
48 termes uniques extraits, dont la moitié sont des noms communs génériques — `the bay`,
`the cellar`, `the garden`, `the lane`, `the village`, `the wharf`, `the estate`. Seuls
les personnages (`john`, `jennie`, `weir mitchell`, …) relèvent du rôle attendu : fournir
un **nom stable pour les éléments importants** du texte, pas une traduction pour chaque
terme rencontré. S'y ajoutent ~21-24 lignes redondantes entre chunks et des instabilités
internes (`the nursery` → « la chambre d'enfant » / « la chambre d'enfants » ;
`debased romanesque` → deux rendus distincts).

Ce chantier construit un audit **par phase, contre sa propre spécification**, dont la
sortie sert à affiner les prompts de `src/template/phase/`.

## Décisions structurantes (hypothèses retenues — les deux questions sont restées sans réponse)

1. **Référence = cahier des charges en prose + métriques nues.** Un fichier de spec par
   phase décrit le rôle attendu et les erreurs typiques ; il est remis à l'agent
   auditeur. Les métriques sont **rapportées sans seuil GO/NO-GO** — le chiffre est un
   constat, le jugement appartient à l'agent. Aucun gold set annoté : non rejouable d'un
   livre à l'autre pour un coût manuel par livre.
2. **Périmètre = glossaire seul, sur un socle générique.** L'infrastructure (résolution
   de source, protocole d'auditeur, rapport, agent) est écrite une fois ; un seul
   auditeur concret est livré. Les autres phases s'ajoutent sans retoucher le socle.
3. **Entrée = un cache de pipeline quelconque** (choix confirmé) : `<epub>_cache/` d'un
   run ordinaire ou `bench/runs/<id>/work/<variant>/cache/`. Découplé du banc, aucun
   appel LLM pour auditer.
4. **Chantier séparé** de `bench/` : nouveau package `src/ebook_translator/audit/`.

## Hors-périmètre

- Les phases analyse littéraire, traduction initiale, raffinement (socle prêt, auditeurs
  non écrits).
- Le cumul inter-runs / suivi de régression dans le temps.
- Toute modification des prompts de `src/template/phase/` — l'audit produit le diagnostic,
  la correction est un chantier suivant.
- Les limites du banc citées en amorce (`Chunks` de `metrics.md` aveugle aux rejets,
  `max_fragments` non réparti, `LLMValidationError` sur segments non reconnus) : hors
  périmètre sauf si l'audit bute dessus.

## Architecture

Nouveau package `src/ebook_translator/audit/` :

| Fichier | Rôle |
| --- | --- |
| `source.py` | `AuditSource` : résout un cache + EPUB source, expose les stores de phase |
| `findings.py` | `Metric`, `Observation`, `Sample`, `AuditFindings` — types de sortie communs |
| `auditor.py` | Protocole `PhaseAuditor` : `phase`, `spec_name`, `run(source) -> AuditFindings` |
| `glossary_auditor.py` | Auditeur de la phase glossaire |
| `report.py` | Écrit `report.md`, `metrics.md`, `samples/` dans le répertoire d'audit |
| `specs/glossary.md` | Cahier des charges du glossaire, en prose, remis à l'agent |
| `__main__.py` | CLI `python -m ebook_translator.audit` |

**Réutilisations directes** (ne rien réécrire) :

- `read_source_fragments()` ([bench/collect.py:123](src/ebook_translator/bench/collect.py))
  pour le texte source depuis l'EPUB, et le motif de lecture de store de
  `read_translations()` (racine legacy + sous-dossier `_v2` via `PhaseBase.BYTE_STORE_SUBDIR`).
- `Glossary` ([glossary.py](src/ebook_translator/glossary.py)) : `get_conflicts()`,
  `get_statistics()`, `collect_entry_with_conflicts()` couvrent déjà confiance, dominance
  et détection de conflits. L'auditeur charge le `.<stem>_glossary.json` du workspace
  plutôt que de recompter à la main.
- `exporter/helper.py` (`save_markdown`, `slugify`) et le style de tableaux Markdown de
  `bench/report.py`.
- `GlossaryExporter._escape_table_cell` pour les cellules.

## Métriques du glossaire

Sources : `cache/glossary/chunk N.md` (une table par chunk), `cache/glossary/_v2/glossary_*.json`
(payload brut par fingerprint de chunk), `.<stem>_glossary.json` (glossaire agrégé), et
l'EPUB source.

| Métrique | Ce qu'elle expose |
| --- | --- |
| Densité | Termes uniques pour 1000 mots source |
| Composition | Répartition par `type` (personnage / lieu / objet / référence culturelle) |
| Suspicion de nom commun | Termes ouverts par un article (`the `, `a `, `an `) ou jamais capitalisés en milieu de phrase dans la source |
| Ancrage source | Occurrences du terme dans le texte source — un terme vu une seule fois n'est pas « récurrent » |
| Redondance inter-chunks | Termes réémis dans ≥2 chunks, et le total de lignes redondantes |
| Instabilité de traduction | Termes portant ≥2 propositions distinctes, avec les variantes (via `get_conflicts()`) |
| Instabilité de classement | Même terme classé sous ≥2 `type` ou ≥2 `sexe` |
| Candidats manqués | Tokens capitalisés récurrents de la source hors début de phrase, absents du glossaire |

Chaque métrique produit aussi ses **exemples** (échantillons bornés) : c'est la matière
que l'agent juge, le chiffre seul ne suffit pas.

Le **catalogue d'erreurs** du rapport regroupe ces observations par catégorie, les classe
par effectif décroissant, avec N exemples chacune. Portée : un run, pas de cumul.

## Étapes

1. **Socle** — `findings.py`, `auditor.py`, `source.py`. `AuditSource` résout cache + EPUB
   (l'EPUB déduit du workspace, surchargeable), vérifie que la phase demandée a un store,
   échoue clairement sinon.
2. **Auditeur glossaire** — `glossary_auditor.py` : lecture des chunks, agrégation,
   les huit métriques ci-dessus avec leurs échantillons.
3. **Spec** — `specs/glossary.md` : rôle attendu, ce qui doit entrer au glossaire et ce
   qui n'y a pas sa place, erreurs typiques, questions que les métriques ne tranchent pas.
4. **Rapport** — `report.py` + `__main__.py`. Sortie dans `audit/<audit_id>/`
   (`report.md`, `metrics.md`, `samples/`, `manifest.json` : cache audité, phase, date).
5. **Tests** — `tests/audit/` : fixtures d'un mini-cache glossaire, une métrique par test,
   plus un test bout-en-bout du CLI sur le run `20260803_210405`.
6. **Agent + skill** — `.claude/agents/phase-auditor.md` et `.claude/skills/phase-audit/SKILL.md`,
   calqués sur `bench-judge` : l'agent lit la spec, le rapport et les échantillons, écrit
   `verdict.md` avec un jugement sur ce que les métriques ne captent pas et une liste
   priorisée de corrections de prompt. Contexte vide, pas d'aveugle à tenir ici.
7. **Doc** — `docs/AUDIT.md` (rôle, différence avec `docs/BENCH.md`, ajout d'un auditeur),
   entrées dans la table de `CLAUDE.md` et `docs/CHANGELOG.md`.

## Vérification

```bash
# Audit du glossaire d'une variante du run existant, sans appel LLM
uv run python -m ebook_translator.audit \
  "bench/runs/20260803_210405/work/t05/cache" --phase glossary

# Le rapport doit retrouver les constats connus :
#   ~48 termes uniques, ~la moitié classés « suspicion de nom commun »,
#   21-24 lignes redondantes, `the nursery` et `debased romanesque` en instabilité
uv run pytest tests/audit/ --no-cov
uv run basedpyright src/          # 0 erreur exigée
uv run pre-commit run --all-files
```

Puis `/phase-audit bench/runs/20260803_210405/work/t05/cache` pour le verdict de l'agent.

## Note d'amorçage

`.claude/implementation/` n'existe pas : sa création (et celle de la branche
`bench-audit` depuis `master`) fait partie du démarrage. `git status` ne montre que
`? src/template` — fichiers non suivis dans le sous-module, déclarés hors travail en cours.
