---
slug: glossary-key-normalization
titre: Normalisation complète des clés du glossaire
statut: validé
execution: direct
créé: 2026-08-14
---

## Intention

**Symptôme** : dette technique n°9 ([docs/TECHNICAL_DEBT.md](../../docs/TECHNICAL_DEBT.md)) —
`Adventurers’ Association` existe sous deux clés (poids 10 et 8) parce que la clé n'est
normalisée que sur la casse. 18 émissions du même terme scindées en deux distributions dont
aucune n'atteint ce que leur somme aurait donné : la convergence, fonction même du glossaire,
est retardée ou empêchée, et le terme est réinjecté deux fois sous deux formes concurrentes.

**But** : normaliser **tous les caractères** dans la clé, en gardant la détection du terme dans
le texte source alignée sur la graphie du livre, pour que la réinjection dans le prompt reste
efficace.

## Critères de réussite

- deux graphies d'un même terme ne différant que par la ponctuation Unicode (apostrophe droite
  vs typographique, tiret, espace) cumulent leur poids sur une clé unique
- le terme réinjecté dans le prompt porte la graphie employée par le livre, pas la forme
  normalisée
- les deux collecteurs (`collect_entry`, `collect_entry_with_conflicts`) retrouvent toujours les
  termes dans le texte du bloc — vérif : `uv run pytest tests/glossary/`
- un cache JSON existant portant les clés dupliquées voit ses entrées **fusionnées** au
  chargement (dit)
- `uv run basedpyright src/` → 0 erreur ; `uv run pytest` passe

## Hors-périmètre

- les templates jinja du glossaire ne sont pas modifiés (dit)
- aucun run LLM de validation attendu : ni bench, ni audit réel — les tests suffisent (dit)
- pas d'outil de migration séparé des caches sur disque ; la fusion se fait au chargement,
  dans `import_from_volume` (dit)

*Non retenu comme hors-périmètre* : une refonte plus large de `glossary.py` n'a pas été exclue
lors de l'arbitrage du 2026-08-14 — elle reste possible si le chantier la rend nécessaire.

## Signaux de dérive

- si le diff sort de `glossary.py`, `glossary_seed.py` et `tests/glossary/`, s'arrêter et en
  reparler (dit)
- si la logique de confiance, de dominance ou de gel des termes convergés se met à changer, ce
  n'est plus ce chantier (dit)

## Contraintes connues de l'utilisateur

- **Aligner sur le livre** : la normalisation sert la détection, pas l'esthétique — la forme
  réinjectée doit correspondre aux termes du livre (dit)
- **Fusionner, pas jeter** : les clés dupliquées des caches existants sont fusionnées (dit)
- **Portée** : « tous les caractères » — NFKC puis table de repli explicite (apostrophes,
  guillemets, tirets, espaces, ellipses) ; **sans** dépouillement des diacritiques, qui
  confondrait des termes réellement distincts en français (dit)
- **Graphie source** : un `source_casing` persisté, symétrique de `translation_casing` — le
  schéma JSON du glossaire change, les caches actuels repartent de la forme normalisée jusqu'à
  réémission des termes (dit)
- **Symétrie existante à réutiliser** : `_bump_casing` / `_preferred_casing` + champ
  `translation_casing` restituent déjà la graphie majoritaire, mais côté traduction uniquement
  (dépôt: src/ebook_translator/glossary.py:215-257, commit 1455354)
- **Cinq sites de normalisation** : `learn()` l.350, `add_user_translation()` l.501,
  `import_from_volume()` l.815, `collect_entry()` l.536-550,
  `collect_entry_with_conflicts()` l.596-602 (dépôt: src/ebook_translator/glossary.py)
- **NFKC ne suffit pas** : mesuré, `NFKC` laisse intacts `’` (U+2019), `–` (U+2013) et `‐`
  (U+2010) — la table de repli est donc indispensable (dépôt: vérifié via
  `unicodedata.normalize`)

## Incertitudes à lever en plan

- aucune restante — les trois ambiguïtés du cadrage (graphie source, portée de la
  normalisation, hors-périmètre) ont été tranchées le 2026-08-14
