---
slug: glossary-key-normalization
titre: Normalisation complète des clés du glossaire
branche: glossary-key-normalization
base: master
statut: terminé
session: 1
execution: direct
plan: .claude/plans/eager-honking-scroll.md
brief: .claude/implementation/glossary-key-normalization.brief.md
créé: 2026-08-14
maj: 2026-08-14
---

## Objectif et périmètre

Repris du brief (`brief:`).

**Symptôme** : dette technique n°9 (`docs/TECHNICAL_DEBT.md`) — `Adventurers’ Association`
existe sous deux clés (poids 10 et 8) parce que la clé n'est normalisée que sur la casse.
18 émissions du même terme scindées en deux distributions dont aucune n'atteint ce que leur
somme aurait donné : la convergence, fonction même du glossaire, est retardée ou empêchée, et
le terme est réinjecté deux fois sous deux formes concurrentes.

**But** : normaliser **tous les caractères** dans la clé, en gardant la détection du terme dans
le texte source alignée sur la graphie du livre, pour que la réinjection dans le prompt reste
efficace.

**Critères de réussite** :
- deux graphies d'un même terme ne différant que par la ponctuation Unicode cumulent leur poids
  sur une clé unique
- le terme réinjecté dans le prompt porte la graphie employée par le livre
- les deux collecteurs retrouvent toujours les termes dans le texte du bloc
- un cache JSON existant aux clés dupliquées voit ses entrées fusionnées au chargement
- `uv run basedpyright src/` → 0 erreur ; `uv run pytest` passe

**Hors-périmètre** :
- ~~les templates jinja du glossaire ne sont pas modifiés~~ — **périmètre élargi le 2026-08-14**
  après l'audit : `glossary_existing_block.jinja` affirme au modèle que les formes listées sont
  « normalisées en minuscules » et lui demande de ne pas les reprendre. C'était vrai avant ce
  chantier, ce ne l'est plus : la consigne annule le bénéfice sur le groupe émergent
- aucun run LLM de validation : ni bench, ni audit réel — les tests suffisent
- pas d'outil de migration séparé des caches sur disque ; la fusion se fait au chargement

**Signaux de dérive** :
- si le diff sort de `glossary.py`, `glossary_seed.py` et `tests/glossary/`, s'arrêter et en
  reparler — **exception validée le 2026-08-14** : l'étape 5 touche `docs/TECHNICAL_DEBT.md` et
  `docs/CHANGELOG.md`, écart signalé et approuvé à la validation du plan
- si la logique de confiance, de dominance ou de gel des termes convergés se met à changer, ce
  n'est plus ce chantier

## Étapes

- [x] 1. `normalize_for_matching` + ses tests — `src/ebook_translator/glossary.py`, `tests/glossary/test_normalisation.py` — vérif: `uv run pytest tests/glossary/test_normalisation.py --no-cov`
- [x] 2. Graphie source persistée (`source_casing`, helpers plats, restitution) — `src/ebook_translator/glossary.py`, `tests/glossary/test_casing.py` — vérif: `uv run pytest tests/glossary/ --no-cov`
- [x] 3. Brancher les cinq sites + propositions de traduction — `src/ebook_translator/glossary.py` — vérif: `uv run pytest tests/glossary/ --no-cov && uv run basedpyright src/`
- [x] 4. Fusion d'un cache existant aux clés dupliquées (cas mesuré de la dette) — `tests/glossary/test_normalisation.py` — vérif: `uv run pytest tests/glossary/test_normalisation.py --no-cov`
- [x] 5. Documentation : retrait de la dette n°9, changelog, docstrings — `docs/TECHNICAL_DEBT.md`, `docs/CHANGELOG.md`, `src/ebook_translator/glossary.py` — vérif: `uv run pre-commit run --all-files`
- [x] 6. Défauts de l'audit : rejet de la clé vide, graphie source compressée, normalisation de l'argument des deux lectures, test de fusion multi-clés — `src/ebook_translator/glossary.py`, `tests/glossary/test_normalisation.py` — vérif: `uv run pytest tests/glossary/ --no-cov && uv run basedpyright src/`
- [x] 7. Consigne du prompt réalignée sur la graphie affichée — `src/template/common/glossary_existing_block.jinja` — vérif: `uv run pytest tests/glossary/ tests/template/ --no-cov`

## État courant

**Chantier clos le 2026-08-14.** Les cinq critères de réussite ont été rejoués en exécution
avant clôture : clé unique pour deux graphies (poids 5, confiance haute), graphie du livre
restituée, collecte identique dans les deux graphies, cache scindé fusionné à 18, `pytest`
849 passés et `basedpyright` 0 erreur.

**Reste en dette, hors périmètre** : `audit/glossary_auditor._normalize` (l.89-98) garde sa
table réduite à deux apostrophes, sans NFKC ni tirets — ses comptages sur-fragmentent désormais
par rapport au glossaire réel. À consigner dans `TECHNICAL_DEBT.md` si l'écart gêne.
**Vérification** : `uv run basedpyright src/ && uv run pytest`
**Notes** : `src/template.old/` (reliquat non versionné du sous-module absorbé) a été supprimé
au démarrage du chantier, avec accord, pour obtenir un arbre propre.

## Journal de décisions

- **2026-08-14** — Périmètre élargi aux templates du glossaire, après audit. *Pourquoi* : la
  consigne de `glossary_existing_block.jinja` dit au modèle de ne pas reprendre les formes
  listées, désormais fausse et annulant le bénéfice du chantier sur le groupe émergent.
  *Rejeté* : en faire une nouvelle dette, qui aurait laissé le critère « graphie du livre »
  servi dans le code et défait dans le prompt.
- **2026-08-14** — Une clé normalisée vide est rejetée à l'apprentissage. *Pourquoi* :
  `text.count("")` vaut `len(text)+1`, donc un terme réduit à des invisibles se collecte dans
  tous les blocs, en tête du tri. *Rejeté* : filtrer à la collecte — le terme fantôme resterait
  en cache et dans les exports.

- **2026-08-14** — Graphie source persistée dans un champ `source_casing`, symétrique de
  `translation_casing`. *Pourquoi* : la réinjection doit montrer au modèle la forme employée par
  le livre, pas la clé normalisée. *Rejeté* : retrouver la graphie dans le texte du bloc au
  moment de la réinjection — rien à persister, mais la graphie n'existerait que pour les blocs
  où le terme apparaît.
- **2026-08-14** — Normalisation = NFKC + table de repli (ponctuation, espaces, largeur nulle),
  `lower()` et non `casefold()`, sans dépouillement des diacritiques. *Pourquoi* : NFKC seul
  laisse intacts `’`, `–` et `‐`, précisément les caractères de la dette ; dépouiller les
  accents confondrait des termes français distincts. *Rejeté* : table de repli seule (laisse
  passer les variantes de compatibilité).
- **2026-08-14** — Les mesures 10/8 de la dette n°9 sont antérieures au gel des termes convergés
  (commit `e159721`) : `learn` plafonne aujourd'hui chaque graphie à `converged_weight()` = 5.
  *Conséquence* : le gain de la fusion ne se mesure pas en cumul brut mais en franchissement du
  seuil de convergence — les tests d'apprentissage sont écrits ainsi. La fusion des caches, elle,
  ne passe pas par `learn` et additionne bien 10 + 8.
- **2026-08-14** — Une entrée `user` conserve la graphie saisie dans son champ `terme`, là où
  elle recevait la clé normalisée. *Pourquoi* : même règle que pour les termes appris, la forme
  réinjectée doit être celle du livre. *Conséquence* : cinq tests encodaient l'ancien contrat
  (`terme` en minuscules) et ont été réalignés.
- **2026-08-14** — La normalisation s'applique aussi aux propositions de traduction, pas
  seulement aux clés sources. *Pourquoi* : le fractionnement frappe les deux côtés à l'identique.
  Écart à la lettre de la dette n°9, signalé et validé.
