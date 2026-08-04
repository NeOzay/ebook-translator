---
slug: bench-audit
titre: Audit d'une phase contre son cahier des charges
branche: bench-audit
base: master
statut: terminé
session: 2
plan: .claude/plans/immutable-puzzling-castle.md
créé: 2026-08-03
maj: 2026-08-04
---

## Objectif et périmètre

**But** : auditer chaque phase du pipeline **individuellement, contre sa propre
spécification**, là où `bench/` ne fait que comparer des variantes entre elles. Sortie
exploitable pour affiner les prompts de `src/template/phase/`.

**Critères de réussite** :

- `ebook-audit <cache> --phase glossary` produit un rapport sans aucun appel LLM ;
- sur `bench/runs/20260803_210405/work/t05/cache`, le rapport retrouve les constats
  mesurés : 48 termes uniques, 28 en `nom-commun-article`, `the nursery` et
  `debased romanesque` signalés en instabilité ;
- `uv run basedpyright src/` → 0 erreur ; tests `tests/audit/` verts.

Le critère « 21-24 lignes redondantes » du plan initial **est retiré** : la mesure était
fondée sur une lecture fausse du glossaire (voir journal). Les 21 réémissions restent
comptées comme métrique, mais ne sont plus un écart.

**Hors-périmètre** :

- Auditeurs des phases analyse littéraire, initiale, raffinement (socle prêt, non écrits).
- Cumul inter-runs / suivi de régression dans le temps.
- Modification effective des prompts `src/template/phase/` — l'audit diagnostique, la
  correction est un chantier suivant.
- Limites connues du banc (`Chunks` de `metrics.md` aveugle aux rejets, `max_fragments`
  non réparti, `LLMValidationError` sur segments non reconnus), sauf blocage rencontré.

## Étapes

- [x] 1. Socle — `audit/findings.py`, `audit/auditor.py`, `audit/source.py`
- [x] 2. Auditeur glossaire — `audit/glossary_auditor.py`, 7 catégories + échantillons
- [x] 3. Spec en prose — `audit/specs/glossary.md`
- [x] 4. Rapport et CLI — `audit/report.py`, `audit/__main__.py`
- [x] 5. Tests — `tests/audit/` (40 tests, couverture 86-100 % par fichier)
- [x] 6. Agent + skill — `.claude/agents/phase-auditor.md`, `.claude/skills/phase-audit/`
- [x] 7. Doc — `docs/AUDIT.md`, `CLAUDE.md`, `docs/CHANGELOG.md`
- [x] 8. Correctifs issus du premier `/phase-audit` réel sur t05
- [x] 9. Ergonomie CLI — sortie console, scripts `ebook-audit` / `ebook-bench`,
      section « Utilisation » de `docs/AUDIT.md`

## État final

**Livré** : `ebook_translator.audit`, un auditeur (glossaire), l'agent `phase-auditor`
et le skill `/phase-audit`. 626 tests passent, `basedpyright src/` à 0 erreur,
`pre-commit` vert.

**Vérification** :

```bash
uv run ebook-audit "bench/runs/20260803_210405/work/t05/cache"
uv run pytest --no-cov                   # 626 passés
uv run pre-commit run --all-files        # tout vert
```

**Ce que le premier audit réel a montré** (verdict complet dans `audit/runs/`, non
versionné) : la phase glossaire produit un inventaire de noms communs, ~13 termes sur 48
satisfont les trois conditions de la spec, et les 7 contre-exemples que la spec cite
nommément sont tous en sortie. Cause désignée : la ligne « Le glossaire doit couvrir :
… » de `glossary_system.jinja`, consigne de couverture sans critère de sélection.

**Suite** : corriger ce prompt. Chantier distinct — `src/template/` est un sous-module,
et l'audit diagnostique là où la correction touche à la production.

## Journal de décisions

- Référence = cahier des charges en prose + métriques nues, sans seuil GO/NO-GO —
  rejouable sur n'importe quel livre, le jugement reste à l'agent.
- Entrée = un cache de pipeline quelconque, pas un `run_id` de banc — découple l'audit
  du banc.
- Package séparé `src/ebook_translator/audit/`, pas une extension de `bench/` —
  objectifs disjoints : audit contre spec vs comparaison de variantes.
- Socle générique mais un seul auditeur écrit, le glossaire — valider le socle sur le
  cas le mieux documenté avant de l'étendre.
- L'ancrage source compte le terme privé de son article — `the cellar` n'apparaît nulle
  part, `cellar` une fois.
- `redondance` ne compte que les réémissions **après convergence** — réémettre est le
  mécanisme d'accumulation de poids, que le prompt réclame explicitement tant que le
  terme n'est pas `high`.
- Les seuils de convergence sont exposés par `glossary.py` (`converged_weight`,
  `DEFAULT_MIN_REINJECTION_WEIGHT`), pas recopiés — la formule de confiance est la
  source de vérité, une copie dériverait.
- Une observation d'effectif nul reste au catalogue avec la liste complète de ses
  sujets — « 0 » était indiscernable de « non mesuré ».
- `program_name()` partagé (`cli.py`) : l'aide nomme la commande réellement tapée, les
  deux points d'entrée (`ebook-audit`, `python -m`) restant valides.
