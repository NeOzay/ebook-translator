# Glossaire — critère d'admission, mesure, casse

## Contexte

L'audit de la phase glossaire sur `bench/runs/20260803_210405/work/t05/cache`
(*The Yellow Wallpaper*, 4 chunks, 48 termes) conclut que la phase **ne tient pas son
cahier des charges sur son critère central**. La spec demande « un nom stable pour les
éléments importants du texte » ; la phase produit un inventaire lexical du bloc courant.
Après tri des faux positifs par l'agent, **36 termes sur 48 (75 %) n'ont rien à
stabiliser** — `the cellar`, `the garden`, `the village`, `ale`, `wine`,
`debased romanesque`.

Symétriquement, le seul objet-motif que la spec cite en exemple — `the yellow wallpaper` —
est émis sous **trois clés distinctes** (`the yellow wallpaper`, `the wallpaper`,
`yellow wallpaper`), à poids 1 chacune. Le terme qui justifie l'existence de la phase est
celui qu'elle ne stabilise pas, et **aucune catégorie du catalogue ne le voit** : chaque
clé est individuellement cohérente.

L'instruction fautive est identifiée : `glossary_system.jinja`, § Consignes, première
puce — « Le glossaire doit couvrir : personnages, lieux, créatures, appellations,
organisations, objets importants, termes techniques, références culturelles. » C'est une
injonction de **couverture par catégories, sans critère d'admission**. Le modèle fait ce
qu'on lui demande : il balaie le bloc et remplit huit cases. Les 60 lignes de « Règles de
catégorisation » disent *comment ranger* un terme, jamais *s'il faut le retenir*.

L'audit a par ailleurs mis au jour un défaut hors prompt : `Glossary.learn` applique
`.lower()` à `proposition_traduction` (`glossary.py:235`). Sur un glossaire dominé par des
anthroponymes, les phases 1 et 2 reçoivent `john`, `jane`, `weir mitchell` en bas de casse.
Aucune métrique ne le remonte.

**Résultat attendu** : un prompt qui sélectionne au lieu de balayer, un auditeur qui reste
capable de mesurer après ce changement, et un glossaire qui ne détruit plus la casse des
noms propres.

## Périmètre

**Dans le périmètre** : `src/template/phase/glossary_system.jinja` (sous-module),
`src/ebook_translator/audit/glossary_auditor.py`, `src/ebook_translator/glossary.py`,
tests associés, un run de vérification sur *The Yellow Wallpaper*.

**Hors périmètre** : la qualité des propositions de traduction (aucune métrique ne
distingue une traduction stable d'une traduction juste) ; le compteur de lignes rejetées
au parsing ; l'incohérence de clé de `self._user` (indexé sans `.lower()` en écriture,
cherché en minuscules en lecture — bug réel, signalé, non traité ici).

## Étape 1 — Prompt : critère d'admission

`src/template/phase/glossary_system.jinja`, § Consignes. Remplacer la puce de couverture
par un critère cumulatif suivi d'une exclusion explicite :

> Un terme n'entre au glossaire que si les trois conditions sont réunies : il **revient**
> dans le livre, sa désignation est **stable** dans la source, et deux traducteurs
> travaillant sur des passages différents pourraient le **nommer autrement**.
>
> N'entrent pas au glossaire : les noms communs génériques, avec ou sans article
> (`the bay`, `the cellar`, `the garden`, `the village`) ; les termes vus une seule fois ;
> les descriptions plutôt que les désignations (`debased romanesque` décrit un style, ce
> n'est pas un nom). Un objet non nommé entre s'il fait motif récurrent dans le texte
> (`the yellow wallpaper`). Dans le doute, n'ajoute pas.

La dernière phrase avant « Dans le doute » est le **contre-poids à ne pas retirer** : le
modèle ne voit qu'un bloc et ne peut pas vérifier la récurrence à l'échelle du livre. Sans
elle, il écarte les motifs légitimes rencontrés pour la première fois — `the pattern` au
chunk 1 — et l'on remplace une sur-extraction par une sous-extraction.

Contrainte de style (`src/template/CLAUDE.md`) : ton déclaratif, pas d'explication du
« pourquoi », une seule occurrence de chaque règle.

## Étape 2 — Prompt : forme canonique du terme

Même fichier, § « Format du tableau » :

> La colonne `terme` porte la forme la plus courte qui identifie l'élément, sans article
> ni déterminant : `yellow wallpaper`, pas `the yellow wallpaper` ni `the wallpaper`. Si
> le même élément peut s'écrire de plusieurs façons, retiens une seule forme et conserve-la
> à chaque émission.

Vise la fragmentation du motif central. Appliquer **après** l'étape 1, sans quoi la
canonicalisation agrège du bruit au lieu de le supprimer.

Commit dans le sous-module `src/template`, puis mise à jour du pointeur dans le dépôt
principal — **deux commits, deux dépôts**.

## Étape 3 — Auditeur : `nom-commun-article` insensible à la canonicalisation

`_leading_article` (`glossary_auditor.py:743`) teste `u.term.startswith(LEADING_ARTICLES)`,
c'est-à-dire l'article **dans la clé émise**. Une fois l'étape 2 appliquée, plus aucune clé
ne porte d'article : le détecteur devient aveugle et l'audit suivant conclura faussement à
la disparition de l'écart. Les cas ne disparaîtront pas pour autant — ils migreront vers
`sans-marque-nom-propre`, dont `_no_proper_noun_evidence` est aujourd'hui le complément
exact (même prédicat, partition sur l'article).

Correctif : décider sur la **source**, pas sur la clé — le terme apparaît-il précédé d'un
article dans le texte ? Réutiliser `_strip_article` (ligne 420) et `_SourceIndex`. La
partition entre les deux catégories reste alors valide avant comme après le changement de
prompt.

## Étape 4 — Auditeur : catégorie `variantes-de-surface`

Nouvelle observation, dans `_observations` (ligne 569). Regrouper les clés par forme
normalisée (`_normalize` ligne 89, puis `_strip_article`) et signaler les groupes de plus
d'une clé, ainsi que les clés dont l'une est sous-chaîne de l'autre. Signale
`the yellow wallpaper` / `the wallpaper` / `yellow wallpaper`, et `the piazza` / `the porch`
qui partagent la proposition « la véranda ».

C'est le défaut le plus grave du run, et le seul qu'aucune catégorie ne relève. Cette
catégorie sert aussi de **contrôle de l'étape 2** : elle doit tomber à 0.

## Étape 5 — Auditeur : `redondance` en limite de mesure

`_premature_reemissions` (ligne 683) rend `count = 0` quand aucun terme n'a convergé — mais
ce 0 n'est pas « cherché et non trouvé », il est **inobservable** : un terme ne pouvant
être émis qu'une fois par chunk, un livre de moins de `converged_weight()` chunks ne peut
faire converger personne. Le plafond réel est plus bas encore : la réinjection exige un
poids ≥ `DEFAULT_MIN_REINJECTION_WEIGHT`, donc un terme n'est réexposé au modèle qu'au 4ᵉ
chunk.

Quand `len(par_chunk) < converged_weight()`, retirer l'observation du catalogue et laisser
la note de limites de mesure la porter — en y ajoutant le seuil de réinjection, absent
aujourd'hui. Même traitement pour la métrique « Termes convergés ». La distinction
zéro-mesuré / non-mesurable est celle qu'impose `docs/AUDIT.md`.

## Étape 6 — Casse des propositions

`Glossary.learn` (`glossary.py:234-243`) minuscule la clé source **et** la proposition.
Minusculer la clé est délibéré : c'est la clé d'agrégation, et `collect_entry` cherche
`terme_lower` dans un texte lui-même minusculé (lignes 387-401). Ne pas y toucher.

Pour la proposition, ne pas se contenter de retirer le `.lower()` : `Jean` et `jean`
deviendraient deux propositions concurrentes et se partageraient le poids, retardant la
convergence — l'inverse du but. Approche retenue :

- Continuer à compter sur la clé minuscule (`translations` inchangé, JSON rétrocompatible).
- Ajouter à `_Entry` un `translation_casing: dict[str, dict[str, int]]` — clé minuscule →
  effectifs des graphies observées.
- `get_translation` et `get_translations_until_confidence` rendent la graphie dominante de
  la proposition dominante ; à défaut d'entrée (cache ancien), la clé minuscule, comme
  aujourd'hui.
- `save` sérialise le nouveau champ ; `import_from_volume` le lit avec `.get(…, {})`, ce
  qui suffit à la rétrocompatibilité.
- Même correction sur `add_user_translation` (ligne 355), qui minuscule une traduction
  saisie à la main.

**La classe `Glossary` n'a aujourd'hui aucun test** — `tests/glossary/` ne contient plus
que `test_convergence.py` et `test_glossary_models.py` (les `test_glossary_filtering.py` et
`test_glossary_validator.py` n'existent qu'à l'état de `.pyc`). Ces tests sont donc à
écrire : apprentissage, agrégation insensible à la casse, restitution de la graphie
dominante, aller-retour de persistance, lecture d'un cache dépourvu du nouveau champ.

Cette étape vient **en dernier** : elle modifie marginalement les propositions réinjectées
dans le prompt de la phase glossaire (via `glossary_existing_block.jinja`), et on ne veut
pas cette variable dans le run de vérification des étapes 1-2. Elle est couverte par les
tests unitaires, pas par le run.

## Étape 7 — Vérification

**Base de comparaison.** Rejouer d'abord l'audit sur le cache actuel avec l'auditeur
corrigé — aucun appel LLM, et c'est la seule façon de comparer avant/après à instrument
égal :

```bash
uv run ebook-audit "bench/runs/20260803_210405/work/t05/cache" --phase glossary
```

**Run de vérification.** Un pipeline réduit à la seule phase glossaire
(`PhasesBuilder().add_glossary_generation(...)`) sur `books/The Yellow Wallpaper.epub`,
cache neuf, puis audit du cache produit. Comparer sur les trois signaux :

| Signal | Avant | Attendu |
|---|---|---|
| Termes uniques | 48 | nettement moins (~12-15 défendables) |
| `nom-commun-article` + `ancrage-faible` | 24 + 24 retenus | effondrés |
| `variantes-de-surface` | 3 clés pour un motif | 0 |
| `candidat-manque` | 0 | **doit rester 0** — c'est le garde-fou de la sous-extraction |

Le livre fait 4 chunks : la convergence reste arithmétiquement hors d'atteinte, et
`redondance` restera en limite de mesure. C'est assumé — la sur-extraction et la
fragmentation, les deux écarts visés, se mesurent sans convergence.

**Contrôles de non-régression** :

```bash
uv run pytest --no-cov
uv run basedpyright src/          # doit rendre 0 erreur
uv run pre-commit run --all-files
```

## Suivi

Fichier de suivi `.claude/implementation/glossaire-precision.md`, branche
`glossaire-precision` depuis `master`. Le sous-module `src/template` est actuellement sur
`master`, propre.
