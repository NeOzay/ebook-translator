# Normalisation complète des clés du glossaire

Brief : `.claude/implementation/glossary-key-normalization.brief.md`

## Context

Dette technique n°9 ([docs/TECHNICAL_DEBT.md](../../docs/TECHNICAL_DEBT.md)). `Glossary.learn()`
indexe un terme par `term["terme"].lower()`, sans autre normalisation. Sur un run réel,
`Adventurers’ Association` existe donc sous deux clés — apostrophe typographique (poids 10) et
apostrophe droite (poids 8). 18 émissions du même terme scindées en deux distributions dont
aucune n'atteint ce que leur somme aurait donné : la convergence, fonction même du glossaire,
est retardée ou empêchée, et le terme part deux fois dans le prompt sous deux formes
concurrentes.

Objectif : une clé qui absorbe **toutes** les variantes de caractères, sans perdre la graphie
que le livre emploie — c'est elle qui doit être réinjectée dans le prompt, sans quoi on montre
au modèle une forme absente du texte.

## État des lieux

Cinq sites normalisent aujourd'hui par un `.lower()` nu, dans
[src/ebook_translator/glossary.py](../../src/ebook_translator/glossary.py) :

| Site | Ligne | Rôle |
|---|---|---|
| `learn()` | 350 | clé d'apprentissage |
| `add_user_translation()` | 501 | clé des entrées `user` |
| `import_from_volume()` | 815 | clé des entrées `user` rechargées (les clés apprises, l.792, ne sont **pas** normalisées) |
| `collect_entry()` | 536-550 | `text.lower()` puis `text.count(terme_lower)` |
| `collect_entry_with_conflicts()` | 596-602 | idem |

Deux acquis à réutiliser plutôt qu'à recréer :

- `_bump_casing` / `_preferred_casing` (l.215-241) + champ `translation_casing` restituent déjà
  la graphie majoritaire d'une proposition — mais **côté traduction uniquement**.
- `import_from_volume` accumule par clé (`self._glossary[source][...] += decayed`) : normaliser
  `source` à la lecture **suffit** à fusionner les clés dupliquées d'un cache existant. Aucun
  outil de migration séparé n'est nécessaire.

Aucun appelant externe n'accède aux clés : `template_renderers.py` (l.196, 264, 701) et
`phases/glossary.py` (l.160) passent par les méthodes publiques ; `glossary_seed.py` passe par
`learn()` et `add_user_translation()`. Le diff reste donc dans `glossary.py` et ses tests.

Mesures Unicode ayant décidé la forme de la normalisation :

- `NFKC` ramène bien les espaces insécables (`\xa0`, ` `) à l'espace, l'ellipse `…` à `...`,
  la pleine chasse à l'ASCII ;
- `NFKC` laisse **intacts** `’` (U+2019), `“ ”`, `– — ‐` (U+2013/2014/2010) et les caractères de
  largeur nulle. Une table de repli explicite est donc indispensable — c'est précisément le cas
  de la dette.

## Approche

### 1. Une fonction de normalisation unique, publique

Dans `glossary.py`, à côté des helpers existants :

```python
def normalize_for_matching(text: str) -> str
```

Enchaînement : `NFKC` → table `str.maketrans` de repli → `lower()` → compression des blancs
(`" ".join(text.split())`).

La table couvre les familles que NFKC ignore : apostrophes (`’ ‘ ‛ ʼ ′` → `'`), guillemets
(`“ ” „ ″ « »` → `"`), tirets (`‐ ‑ ‒ – — ― −` → `-`), largeur nulle (`​-‍`, `﻿`
→ supprimés).

Deux points arrêtés :

- **`lower()`, pas `casefold()`** — cohérence avec le décompte des propositions, déjà en
  `lower()` (l.364). `casefold` fusionnerait `Straße`/`strasse`, ce qui dépasse ce chantier.
- **Pas de dépouillement des diacritiques** (décidé au cadrage) : confondre `côte` et `cote`
  ferait plus de dégâts que le fractionnement qu'on répare.

C'est la **même** fonction qui normalise la clé et le texte du bloc côté collecteurs — c'est ce
qui garantit que les termes normalisés restent trouvables. La compression des blancs a un effet
de bord bienvenu : un terme coupé par un retour à la ligne redevient détectable.

*Note, hors périmètre* : `audit/glossary_auditor.py` a sa propre `_normalize` privée (l.89-98),
table d'apostrophes réduite à deux caractères. Elle pourrait consommer cette fonction plus tard ;
ce chantier n'y touche pas.

### 2. La graphie source, symétrique de la graphie de traduction

Nouveau champ dans `Glossary._Entry` : `source_casing: dict[str, int]` — surface observée →
effectif. Un seul niveau, contrairement à `translation_casing` : il n'y a qu'un terme par entrée,
là où il y a plusieurs propositions.

Pour éviter deux mécanismes parallèles, extraire le cœur de `_bump_casing` / `_preferred_casing`
en deux helpers plats (`_bump_surface(counts, surface)`, `_preferred_surface(counts, fallback)`)
et réécrire les deux fonctions existantes par-dessus — elles gardent leur signature et leurs
appelants.

- `learn()` alimente `source_casing` avec `term["terme"]` brut, tel que le LLM l'a copié du livre.
- `get_translation()` (l.429) et `get_translations_until_confidence()` (l.457) renvoient
  `_preferred_surface(entry["source_casing"], source_term)` au lieu de la clé nue.
- Repli sur la clé quand rien n'est mémorisé — exactement ce que fait déjà `_preferred_casing`
  pour les caches antérieurs au suivi de casse.

Conséquence assumée : `learn()` sort tôt sur un terme convergé, donc la graphie cesse d'être
alimentée après convergence. La forme majoritaire est alors déjà fixée.

### 3. Brancher les cinq sites

Remplacer chaque `.lower()` de clé par `normalize_for_matching(...)`, y compris **les clés
apprises de `import_from_volume`** (l.792), aujourd'hui non normalisées — c'est le geste qui
fusionne les caches existants.

Les propositions de traduction (l.364) passent par la même fonction : le fractionnement
d'`Adventurers’ Association` frappe identiquement `l’Association` côté cible, et
`_preferred_casing` restitue déjà la graphie.

Les entrées `user` gardent leur graphie d'origine dans le champ `terme` (aujourd'hui écrasé par
la clé, l.503) et sont indexées sur la clé normalisée.

Simplification qui tombe d'elle-même : dans les collecteurs, `terme_lower = terme.lower()`
disparaît — la clé itérée **est** déjà normalisée.

### 4. Documentation

L'entrée n°9 de `docs/TECHNICAL_DEBT.md` est retirée et le changement noté dans
`docs/CHANGELOG.md`. Les docstrings de `add_user_translation` (l.482-486) et `learn` (l.331-333),
qui affirment « la comparaison porte sur la forme minuscule », sont réalignées.

## Étapes

- [ ] 1. `normalize_for_matching` + ses tests — `src/ebook_translator/glossary.py`, `tests/glossary/test_normalisation.py` — vérif: `uv run pytest tests/glossary/test_normalisation.py --no-cov`
- [ ] 2. Graphie source persistée (`source_casing`, helpers plats, restitution) — `src/ebook_translator/glossary.py`, `tests/glossary/test_casing.py` — vérif: `uv run pytest tests/glossary/ --no-cov`
- [ ] 3. Brancher les cinq sites + propositions de traduction — `src/ebook_translator/glossary.py` — vérif: `uv run pytest tests/glossary/ --no-cov && uv run basedpyright src/`
- [ ] 4. Fusion d'un cache existant aux clés dupliquées (cas mesuré de la dette) — `tests/glossary/test_normalisation.py` — vérif: `uv run pytest tests/glossary/test_normalisation.py --no-cov`
- [ ] 5. Documentation : retrait de la dette n°9, changelog, docstrings — `docs/TECHNICAL_DEBT.md`, `docs/CHANGELOG.md`, `src/ebook_translator/glossary.py` — vérif: `uv run pre-commit run --all-files`

## Vérification d'ensemble

```bash
uv run basedpyright src/          # 0 erreur
uv run pytest                     # suite complète, gate de couverture à 80 %
```

Le cas de la dette, rejouable directement :

```python
g = Glossary()
for _ in range(10): g.learn({"terme": "Adventurers’ Association", ...})
for _ in range(8):  g.learn({"terme": "Adventurers' Association", ...})
assert len(g) == 1
assert g.get_translation("adventurers' association")["weight"] == 18
assert g.get_translation("adventurers' association")["terme"] == "Adventurers’ Association"
```

Aucun run LLM, bench ou audit n'est attendu (hors-périmètre du brief).
