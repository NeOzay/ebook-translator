---
slug: glossary-seeding
titre: Préremplissage du glossaire pour test sur livres longs
branche: glossary-seeding
base: master
statut: terminé
session: 3
plan: /var/home/Benoit/projects/ebook-translator/.claude/plans/cheerful-hugging-church.md
créé: 2026-08-05
maj: 2026-08-09
---

## Objectif et périmètre

**But** : outiller le préremplissage du glossaire pour exercer ses mécanismes de sélection sans
attendre qu'un run complet de livre long les produise, et lever les deux défauts qui l'empêchent
de fonctionner à cette échelle.

**Pourquoi maintenant** : la convergence est bornée par le facteur de masse `w / (w + 2)` — 5
émissions unanimes pour la confiance haute, 3 pour la réinjection. Sur *The Yellow Wallpaper*
(seul livre testé), aucun terme ne converge : les mécanismes ne sont pas exercés.

**Mesures d'entrée** (`books/.Chillin' … Volume 02 …_glossary.json`, 329 termes) :

| Mesure | Valeur |
| --- | --- |
| Confiance `high` / `medium` / `low` | 37 / 23 / 269 |
| Poids médian | 1 (218 termes vus une seule fois) |
| Termes retenus par `get_translation` (→ prompts phases 1/2) | 319 / 329 |

**Critères de réussite**
- Un fichier de seed TOML produit un `Glossary` dont les termes tombent dans les trois groupes
  attendus de `glossary_existing_block.jinja`, vérifié sur le **prompt rendu**.
- Une entrée `user` préremplie est retrouvée dans le texte et exclue des entrées apprises.
- Un run de banc sur livre long démarre avec un glossaire seedé et produit un audit exploitable.

**Hors-périmètre**
- Le filtre `dominance ≥ 0.95` de `get_translation` (97 % des termes passent) — objet de mesure,
  pas cible de correction : on ne change pas la politique avant de l'avoir observée.
- Le tri de `collect_entry` (occurrences avant fiabilité).
- La piste de cache « bloc validés append-only » — dépend des résultats.
- ~~Toute refonte de `glossary_system.jinja`.~~ **Périmètre élargi le 2026-08-09** (décision
  utilisateur) à la seule clause d'admission des termes validés, cause mesurée du résultat
  central du banc — cf. étape 7 et entrée 11 de `docs/TECHNICAL_DEBT.md`. Le reste du fichier
  (structure, format, exemples) demeure hors-périmètre.

## Étapes

- [x] 1. Corriger la casse des entrées `user` — `src/ebook_translator/glossary.py`
- [x] 2. Module de seed déclaratif TOML — `src/ebook_translator/glossary_seed.py`
- [x] 3. Plafonner `collect_entry_with_conflicts` — `src/ebook_translator/glossary.py`
- [x] 4. Câblage builder et banc — `pipeline/builder.py`, `bench/config_glossaire_seed.py`
- [x] 5. Documentation — `docs/`, `src/template/CLAUDE.md`
- [x] 6. Run réel sur livre long + audit `/phase-audit` (commit: 2bee730 + verdict)
- [x] 7. Empêcher les termes convergés de réapprendre — `glossary.py` (prompt tenté puis annulé)

## État courant

**Chantier clos le 2026-08-09.** Laissés de côté, sans engagement : les deux autres ajustements
proposés par l'audit — règle « sans article » sur `proposition_traduction`, admission réservée à la
première mention (l'auditeur signale lui-même que le second menace le rappel). La dette relevée en
chemin est consignée en entrées 11 à 14 de [docs/TECHNICAL_DEBT.md](../../docs/TECHNICAL_DEBT.md).

**Étape 7 — la consigne de prompt a échoué, le filtre Python tient.** Trois runs comparables
(corpus, seed et modèle identiques), poids cumulé des 11 termes seedés en `valide` :

| Run | Poids des 11 validés | Uniques `preremp` | Uniques `froid` |
| --- | --- | --- | --- |
| `20260809_170606` base | 125 | 161 | 186 |
| `20260809_173125` règle prioritaire dans le prompt | 123 | 157 | 155 |
| `20260809_175457` filtre dans `learn()` | **55** = 11 × 5 | 169 | 176 |

La règle de prompt a été **annulée** : sans effet mesurable et coûteuse en rappel. Un chunk de
`173125` montre `flio` et `belano` listés comme validés, la règle prioritaire présente dans les
consignes, et le modèle les émettant dans la même réponse — la contradiction d'admission n'était
donc pas la cause, contrairement à ce qu'avançait l'audit.

Le filtre `learn()` est déterministe : les 11 termes restent exactement à leur poids de seed.
Écart de `froid` entre les trois runs (186 / 155 / 176) : ordre de grandeur de la variabilité de
génération à température 0.5, utile pour lire les prochains bancs.

**Verdict d'audit** (`audit/runs/20260809_171114-glossary/verdict.md`, variante `preremp`) — la
phase tient son rôle de base (158 termes, 41 convergés, 525 lignes sans incident de format) mais
échoue sur la non-réémission et la stabilité des clés. Après tri des faux positifs, l'union
instruite tombe de 118 termes touchés à ~60-70.

**Cause racine du résultat central, trouvée par l'audit** : `glossary_system.jinja:29` admet un
terme « désigné plusieurs fois dans le bloc **ou figure déjà au glossaire fourni** ». Le glossaire
fourni contient le groupe des validés, que `glossary_existing_block.jinja` déclare à ne pas
réémettre. **Deux consignes contradictoires dans le même prompt**, le modèle suit la permissive.
Ce n'est pas la troncature à 80 termes (médiane réinjectée : 10 par bloc).

**Second défaut de clé — l'apostrophe.** `adventurers' association` (droite) et
`adventurers’ association` (typographique) coexistent comme deux entrées, poids 8 et 4 : `Glossary`
ne normalise que la casse. Le seed emploie la forme typographique, celle du livre.

**Banc réel passé** — `bench/runs/20260809_170606`, 43 blocs × 2 variantes, 86 appels, 0 rejet,
~2 min par variante, tokens d'entrée quasi identiques (246k vs 246k).

*Le préremplissage stabilise, mais la consigne d'exclusion ne tient pas à l'échelle.*

| Catégorie d'audit | froid | preremp |
| --- | --- | --- |
| `classement-instable` | 43 | **16** |
| `variantes-de-surface` | 59 | **42** |
| `ancrage-faible` | 52 | **40** |
| `traduction-instable` | 13 | **25** |
| `candidat-manque` | 109 | 118 |
| Termes uniques / convergés | 186 / 51 | 158 / 41 |

**Résultat central — « NE PAS inclure » est ignoré.** Sur les 11 termes seedés en `valide` (w=5,
donc listés comme stables et exclus de la sortie attendue), **10 ont été réémis**, jusqu'à 13 fois
pour `flio` (w final 18). Seul `klyrode` a été respecté. La fumée, sur un chunk unique, montrait
l'inverse : le comportement ne se juge donc pas à petite échelle.

**L'arbitrage fonctionne, mais l'article fractionne les poids.** La dominante seedée l'emporte
partout, sauf que le modèle produit des variantes sans article — `héros` / `le héros`,
`ténébreux` / `le ténébreux`. Sur `golden-haired hero`, la forme sans article (18) **dépasse** celle
du seed avec article (6). C'est le fractionnement que le glossaire existe pour empêcher, et il
explique à lui seul la hausse de `traduction-instable`.

**Seed du banc réel** — `bench/seeds/chillin_vol01.toml`, 36 termes dérivés de la terminologie du
tome : 11 validés, 10 à arbitrer, 15 émergents, tous vérifiés présents dans le texte. Charge
mesurée : 44 blocs, médiane 10 termes réinjectés par bloc, 18 au plus.

**Fumée passée** — `bench/runs/20260809_164222` (après correction de la casse). Les cinq canaux
validés en conditions réelles :

| Canal | Résultat |
| --- | --- |
| `flio` validé | non réémis par `seede`, réémis par `froid` — la consigne d'exclusion porte |
| `dark one` à arbitrer | dominante confirmée (3 → 4), aucune 3ᵉ forme ; `Citadel of the Dark One` reste cohérent chez `seede`, diverge chez `froid` |
| `balirossa` user | émis par le modèle mais **absent** des entrées apprises — le correctif de l'étape 1 tient |
| `rys` user → `Lys` | traduction divergente : le modèle propose `Rys`, l'entrée tient, `glossary["rys"]` reste vide |
| `gholl` émergent | a révélé la perte de casse, voir ci-dessous |

**Défaut corrigé — toutes les traductions étaient minusculées.** Le doublon `gholl` observé en
fumée n'était qu'un symptôme. Cause réelle : `glossary_models.py:110` typait le 4ᵉ champ de
`Entree` en `NormStr`, dont le `BeforeValidator` applique `.lower()`. Légitime pour `terme`, qui
sert de clé au glossaire ; faux pour `proposition_traduction`, qui finit dans le texte traduit.
`translation_casing` ne recevait donc **jamais** de casse issue du LLM — mesuré sur le run à froid :
**0 des 21 termes** conservait une majuscule, et `get_translation('flio')` rendait `flio`.

Le doctest de `LLMGlossaryModel` documentait le comportement correct (`'Alice'`) et **échouait** :
les doctests ne sont pas branchés sur pytest. Deux tests entérinaient le bug (`lapin blanc`,
`armée des ténèbres`).

Correctif : `WsStr` (espaces réduits, casse préservée) dans `template/types.py`, appliqué au seul
champ de traduction. Vérifié en fumée (`bench/runs/20260809_164222`) — `Flio`, `Uliminas`,
`le Ténébreux`, `Gholl` corrects **dans les deux variantes**, y compris à froid.

La reformulation de `glossary_existing_block.jinja` (formes listées annoncées comme normalisées,
« une seule ligne par terme ») est conservée : elle réduit le dédoublement sans le supprimer
— sur deux runs, un avec doublon, un sans.

**Configs** :

| Config | Livre | Variantes | Coût |
| --- | --- | --- | --- |
| `config_glossaire_smoke.py` | extrait chap. 3_1 du Vol 01, ~8000 car., 1 chunk | `froid` vs `seede` (`smoke.toml`) | ~2 appels ✅ |
| `config_glossaire_seed.py` | `Chillin' Vol 01`, 19 Mo, 44 blocs | `froid` vs `preremp` (`chillin_vol01.toml`) | ~88 appels |

L'extrait de fumée se régénère par `uv run python bench/make_extrait_smoke.py` : `books/` étant
gitignoré, un corpus non reproductible est ce qui a fait perdre celui de la session 2.

Les deux ne font tourner que la **phase glossaire** — ni analyse littéraire ni traduction, et donc
pas de run d'amorçage : rien à partager, et la phase comparée ne doit jamais l'être. `ebook-audit`
lit le cache sans appel LLM.

Le seed de fumée exerce les quatre canaux en un chunk, avec les attendus notés dans
`bench/seeds/smoke.toml` — vérifié sur le prompt rendu : `flio` en validé, `dark one` en conflit à
arbitrer (`le Ténébreux` 3 / `l'Obscur` 2), `gholl` en forme seule, `balirossa` hors du bloc.

**Vérification** : `uv run pytest --no-cov -q` (705 passent), `uv run basedpyright src/` (0 erreur),
`uv run python -m doctest src/template/phase/glossary_models.py` (silencieux)

**Mesures utiles** (relevées session 2 sur `Chillin' Vol 02`, 329 termes, 43 blocs de 8000
caractères — le fichier lui-même est perdu, les chiffres restent la référence de dimensionnement) :
bloc « Glossaire existant » = **828 tokens médians, 1084 max**, contre ~1200 tokens de consignes
stables — soit ~40 % d'un prompt système que son contenu variable empêche de mettre en cache.
Termes injectés par bloc : médiane 37, **max 54**.

**Notes**
- L'étape 1 a révélé un **troisième** point de casse, non prévu au plan : `learn()` court-circuitait
  sur `term["terme"]` brut, si bien qu'une entrée `user` ne protégeait pas le terme des propositions
  du LLM. Corrigé avec les deux autres — `tests/glossary/test_user_entries.py` (7 tests).
- Écart au plan sur le format : la table TOML est `[[entree]]`, pas `[[terme]]` — la seconde forme
  aurait donné une clé `terme` dans une table `terme`.
- `load_seed` ne fixe **pas** `cache_path` : contrairement à ce que prévoyait le plan, cela
  n'apporterait aucune protection (`_glossary_export_path` ne bascule que si la source *est* la
  cible d'export, ce qu'un `.toml` ne peut pas être) et exposerait le seed à un `save()` sans
  argument. Le fichier est protégé par son extension.

## Journal de décisions

- **2026-08-09** — La non-réémission des termes convergés est traitée dans `learn()`, pas par le
  prompt, et le gel est **total**. *Pourquoi* : deux formulations de consigne ont échoué à la
  mesure ; ne compter que les divergences ferait chuter la confiance d'un terme stable au premier
  désaccord tardif. *Acté* : la convergence est un état absorbant, une entrée `user` masque un
  terme gelé sans modifier sa distribution.
- **2026-08-09** — `proposition_traduction` passe de `NormStr` à `WsStr` : la casse d'une traduction
  est préservée, seule la clé `terme` reste normalisée. *Pourquoi* : la normalisation détruisait la
  casse de tous les noms propres appris (0/21 sur un run à froid).
- **2026-08-09** — Le banc mesure un préremplissage **contrôlé** (`bench/seeds/chillin_vol01.toml`)
  et non l'héritage d'un tome au suivant. *Pourquoi* : le corpus du plan est perdu, `books/` étant
  gitignoré. *Rejeté* : run à froid puis réinjection sur le même livre — coût doublé et circulaire.
- **2026-08-05** — Le seed s'exprime en **niveaux** (`valide` / `arbitrer` / `emergent`) et s'applique
  via `learn()`. *Pourquoi* : les niveaux calquent les trois groupes de
  `glossary_existing_block.jinja`, et `learn()` garde distributions, graphies et cache cohérents.
  *Rejeté* : JSON natif du glossaire, illisible à écrire à la main.
- **2026-08-05** — La troncature trie par **groupe de réinjection** (`arbitrer` > `emergent` >
  `valide`) avant la fréquence. *Pourquoi* : un émergent est rare par construction ; le couper pour
  sa rareté le condamne à rester invisible, donc réémis en variante, donc jamais convergé.
  *Coût* : `reinjection_group` duplique en Python le découpage du template, signalé des deux côtés.

### Décisions antérieures

- Le préremplissage reprend les poids tels quels, `decay` écarté — la confiance dérivant déjà du
  poids, l'atténuer mélange deux façons de dire la même chose (`decay=0.1` renvoie 326 termes
  sur 329 en « émergent »). Chantier suivant : refaire `import_from_volume` sur la confiance.
- Les bancs ne font tourner que la phase glossaire, sans run d'amorçage — la phase comparée ne doit
  jamais être partagée, et les phases aval tripleraient le coût.
- Plafond sur `collect_entry_with_conflicts` plutôt que filtre de poids — un terme léger invisible
  est réémis en variante ; le plafond ne mord que sur un glossaire prérempli.
- `glossary_existing_block.jinja` reste dans le `_system` — le cache porte sur le préfixe de la
  requête, le bloc est en dernière position, le déplacer serait neutre en coût.
- `load_seed` ne fixe pas `cache_path` — sans bénéfice, et exposerait le seed à un `save()` sans
  argument ; le fichier est protégé par son extension.
