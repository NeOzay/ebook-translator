---
slug: glossaire-precision
titre: Glossaire — critère d'admission, mesure, casse
branche: glossaire-precision
base: master
statut: terminé
session: 1
plan: .claude/plans/resilient-gathering-otter.md
créé: 2026-08-04
maj: 2026-08-04
---

## Objectif et périmètre

**But** : faire sélectionner le prompt de la phase glossaire au lieu de balayer, garder
l'auditeur capable de mesurer après ce changement, et cesser de détruire la casse des
propositions de traduction.

**Origine** : audit `audit/runs/20260804_200629-glossary/verdict.md` — 36 termes sur 48
(75 %) n'ont rien à stabiliser ; le motif central `the yellow wallpaper` est émis sous
trois clés à poids 1, ce qu'aucune catégorie ne relève.

**Critères de réussite** : tous tenus, confirmés sur 4 runs.

**Hors-périmètre** : la qualité des propositions de traduction ; le compteur de lignes
rejetées au parsing ; l'incohérence de clé de `Glossary._user` (écrit sans `.lower()`,
lu en minuscules — bug réel, signalé, non traité ici).

## Étapes

- [x] 1. Prompt : critère d'admission — `src/template/phase/glossary_system.jinja`
- [x] 2. Prompt : forme canonique du terme (sous-module `78c9d27`, pointeur `a31e42b`)
- [x] 3. Auditeur : `nom-commun-article` décidé sur la source **en plus de** la clé
- [x] 4. Auditeur : catégorie `variantes-de-surface`
- [x] 5. Auditeur : `redondance` en limite de mesure quand la convergence est hors d'atteinte
- [x] 5bis. Réinjection à trois groupes — `glossary.py`, `glossary_existing_block.jinja`
- [x] 6. Casse des propositions — `glossary.py` + tests (la classe `Glossary` n'en avait aucun)
- [x] 7. Vérification : 8 runs de banc, deux modèles (commit `3aa953a`)

## Résultat

Audit du cache t05 à instrument corrigé (`audit/runs/20260804_203018-glossary`) contre le
run de vérification (`bench/runs/20260804_210909`) :

| Signal | avant | deepseek | mistral |
|---|---|---|---|
| Termes uniques | 48 | 19 | 14 |
| Densité / 1000 mots | 7,72 | 3,06 | 2,25 |
| Union touchée | 44/48 (92 %) | 14/19 (74 %) | 9/14 (64 %) |
| `nom-commun-article` | 29 | 6 | 4 |
| `ancrage-faible` | 25 | 11 | 8 |
| `variantes-de-surface` | 10 | **0** | **0** |
| `candidat-manque` | 0 | **0** | **0** |

`yellow wallpaper` est une clé unique de poids 4 contre trois clés de poids 1 ; `nursery`
passe à 3 et cesse d'osciller. Les deux modèles convergent : le critère d'admission n'est
pas calé sur l'un d'eux.

**Répétabilité** — 4 runs par état, lignes émises :

| État du prompt | deepseek | étendue | noyau 4/4 | vus 1×/4 | mistral |
|---|---|---|---|---|---|
| retenu (`78c9d27`) | 41, 43, 41, 44 | **3** | 12 | 19 | 36, 36, 0, 37 |
| + 3 ajustements de finition | 41, 60, 74, 83 | **42** | 10 | 48 | 39, 36, 5, 30 |

Les trois ajustements de finition sont **abandonnés** : étendue ×14, termes vus une seule
fois de 19 à 48. Ils ne laissent aucune trace dans le code.

## Reste à trancher

- `debased romanesque` et `delirium tremens` sont dans le noyau 4/4 des **deux** modèles,
  alors que le premier figure nommément dans la liste d'exclusion du prompt. Défauts
  systématiques, pas du bruit. Une reformulation abstraite de la clause a été essayée et
  dégrade : le sujet mérite sa propre itération.
- **La casse ne vient pas du code** : `translation_casing` fonctionne et persiste, mais les
  deux modèles émettent `john`, `weir mitchell` en minuscules — déjà le cas dans le cache
  t05, antérieur au chantier. Une consigne de casse dans le prompt a été essayée : ignorée
  par les deux modèles, et elle entre en conflit avec la forme canonique. Piste restante :
  restaurer la casse depuis le texte source à l'export, l'auditeur sachant déjà repérer les
  mots capitalisés en milieu de phrase.
- Mistral encadre sa sortie de ``` ``` ``` — 1 ligne écartée sur ~11 par chunk. Retirer la
  clôture de l'exemple du prompt supprime le symptôme mais déstabilise le format ; à
  reprendre autrement.
- Dette technique n° 10 : le banc ne capture aucun journal, déclare `status: "ok"` un run
  sans appel LLM, et n'offre aucun plafond de débit par fournisseur.

## Journal de décisions

- **2026-08-04** — La fréquence d'apparition sur N runs remplace le comptage d'un run comme
  métrique de comparaison. *Pourquoi* : à n=1, l'écart entre deux états de prompt tombe dans
  l'étendue du bruit (41–83 lignes pour un même prompt) ; trois conclusions ont dû être
  retirées. *Rejeté* : comparer des runs isolés.
- **2026-08-04** — Tous les termes du bloc sont réinjectés ; le poids ne décide plus que du
  détail montré (forme seule en deçà de 3, propositions au-delà). *Pourquoi* : un terme vu
  une fois par bloc n'atteignait jamais le poids 3, donc restait invisible et était réémis
  sous une variante qui divisait son poids. *Rejeté* : abaisser le seuil, qui aurait ancré
  le modèle sur des propositions isolées.
- **2026-08-04** — Les conditions d'admission portent sur le **bloc**, pas sur le livre.
  *Pourquoi* : chaque appel LLM est isolé ; le seul canal inter-appels est
  `glossary_existing_block.jinja`. *Rejeté* : « revient dans le livre », invérifiable par le
  modèle.
- **2026-08-04** — Dérogation de récurrence pour les noms propres. *Pourquoi* : la spec cite
  `weir mitchell`, mentionné une seule fois, comme entrée légitime. *Rejeté* : une règle de
  récurrence uniforme.
- **2026-08-04** — `nom-commun-article` retient l'article de la clé **ou** celui de la
  source. *Pourquoi* : la source seule déplaçait 10 termes vers `sans-marque-nom-propre`,
  rendant l'avant/après incomparable. *Rejeté* : substituer un signal à l'autre.

### Décisions antérieures

- Vérifier sur *The Yellow Wallpaper*, phase glossaire seule — comparable à l'audit t05,
  coût minimal, et les deux écarts visés se mesurent sans convergence.
- Agréger la casse sur la clé minuscule plutôt que retirer le `.lower()` — sinon `Jean` et
  `jean` se partagent le poids et retardent la convergence.
