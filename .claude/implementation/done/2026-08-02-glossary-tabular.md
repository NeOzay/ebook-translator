---
slug: glossary-tabular
titre: Glossaire — format tabulaire délimité en sortie LLM
branche: glossary-tabular
base: master
statut: terminé
session: 1
plan: /home/debian/projects/ebook-translator/.claude/plans/snuggly-dancing-prism.md
créé: 2026-08-02
maj: 2026-08-02
---

## Objectif et périmètre

**But** — remplacer l'enveloppe JSON de la sortie LLM de la phase glossaire par un
format tabulaire délimité (`terme|type|sexe|proposition`, terminé par `[=[END]=]`).
Le canal LLM seul change ; la persistance sur disque reste JSON.

**Critères de réussite**

- `uv run pytest --no-cov` vert (il ne collecte même pas aujourd'hui, cf. étape 0)
- `uv run basedpyright src/` à 0 erreur
- tokens de sortie de la phase glossaire mesurés en baisse d'environ 45 % sur un run réel
- les entrées arrivent toujours dans le `Glossary` et dans les Markdown `chunk N.md`

**Hors-périmètre**

- Phase 0 / `analyze_chapter_layered_models.py` — structure imbriquée, non tabulaire
- Le format de persistance (`MemoizedChunkPersister`) — reste JSON
- Les incohérences relevées dans `glossary.py` (`save()` asymétrique, `_user` non
  normalisé, appel mort dans `get_translations_until_confidence`)
- La couverture de test de `Glossary` lui-même (15 % aujourd'hui)

**Deux dépôts** — `src/template` est un sous-module (`NeOzay/ebook-translator-template`).
Les étapes 0 à 2 s'y déroulent (branche + commits dans le sous-module, puis bump du
pointeur côté repo principal) ; les étapes 3 à 5 sont dans le repo principal.

## Étapes

- [x] 0. Réécrire `template/phase/translation_models.py` — `src/template/phase/`, spec = `tests/template/test_translation_models.py` (385 tests verts, basedpyright 0 erreur)
- [x] 1. Format tabulaire dans `LLMGlossaryModel` — `src/template/phase/glossary_models.py`
- [x] 2. Section « Format du tableau » du prompt — `src/template/phase/glossary_system.jinja`
- [x] 3. Basculer `GlossaryPhase` sur la voie texte — `src/ebook_translator/pipeline/phases/glossary.py`
- [x] 4. Tests + mesure — `tests/glossary/test_glossary_models.py` (23 tests) ; mesure statique faite, run réel restant
- [x] 5. Documentation — `src/template/CLAUDE.md`, `CLAUDE.md`, `docs/TEMPLATES.md`, `docs/ARCHITECTURE.md`, `docs/CHANGELOG.md`

## État courant

**Prochaine action** — une seule chose reste ouverte : la **mesure sur un run réel**.
Elle demande une `API_KEY` et un appel payant, donc elle appartient à l'utilisateur :
lancer la phase glossaire seule sur l'EPUB d'`examples/`, cache vidé, et comparer les
tokens de sortie au relevé statique ci-dessous.

**Vérification** — `uv run pytest --no-cov` (412 passés), `uv run basedpyright src/`
(0 erreur), `uv run pre-commit run --all-files` (tout vert).

**Mesure statique** (`cl100k_base`, chunk de 30 entrées) :

| | avant | après | delta |
|---|---:|---:|---:|
| Entrée / appel (prompt système + schéma injecté) | 1335 | 1024 | −23 % |
| Sortie / appel (30 entrées) | 800 | 394 | −51 % |

Le prompt système grossit de 75 tokens (le format doit désormais y être décrit), très
largement compensé par les 386 tokens de schéma JSON qui ne sont plus injectés.

**Notes**

- Étape 0 : le déblocage a demandé quatre correctifs, pas un seul —
  `phase/translation_models.py` réécrit, l'import `GlossaryEntry` de
  `template_params.py` redirigé vers `phase/glossary_models.py`,
  `ConvertibleModel.target_adapter()` réparé, et `AnalyseChapter` fait dériver de
  `ConvertibleModel`.
- **Dette révélée, non traitée** : `TranslateParams.literary_context` est typé
  `AnalyseChapter` (fiche stratifiée) mais `common/literary_context_block.jinja` lit
  encore les champs plats d'`AnalyseLitteraire` — le bloc de contexte littéraire se rend
  donc vide dans les prompts des phases 1 et 2. C'est la dette n°5 de
  `docs/TECHNICAL_DEBT.md` ; `common/literary_context_layered_block.jinja` existe mais
  n'est branché nulle part. `AnalyseLitteraire` (`template/types.py`) n'a plus aucun
  consommateur.
- Mesure de référence (`cl100k_base`, 5 entrées réalistes) : JSON compact 22,4 tok/entrée,
  JSON indenté 33,0, tabulaire `|` 12,4. Plus 439 tokens de schéma injectés en entrée à
  chaque appel par `Mode.JSON`, qui disparaissent.

## Journal de décisions

Journal compacté à la clôture — une ligne par décision, décision + pourquoi.

- Délimiteur `|` sans quoting plutôt que CSV RFC4180 — le `|` n'apparaît pas en prose
  littéraire, donc aucun guillemet réintroduit et un format à géométrie constante.
- Ligne malformée écartée avec un WARNING, sans retry LLM — le glossaire est un agrégat
  pondéré sur tout le livre, et un retry rognerait le gain de tokens visé.
- La validation par ligne vit dans le validator `mode="before"`, pas dans les `Literal`
  Pydantic — ceux-ci font échouer le modèle entier sur une seule ligne fautive.
- Puces et numérotations en tête de ligne nettoyées, pas écartées — elles passaient le
  contrôle de cardinalité et faisaient apprendre un terme `- alice`.
- Un bloc sans terme est une liste vide valide, mais une réponse dont *toutes* les lignes
  sont illisibles fait échouer le chunk — distinguer « rien à extraire » de « format
  ignoré », que le rejet silencieux confondrait.
- `ConvertibleModel.target_adapter()` lit `_build_impl` et non `build` — `build` est
  `@final` et annoté `-> TD`, TypeVar jamais résolue, donc l'adapter dégénérait en `Any`.
- `AnalyseChapter` dérive de `ConvertibleModel[AnalyseChapter]` — `PhaseBase` borne `M`
  sur `ConvertibleModel` et la fiche est déjà sa propre vue `DT`.
- Réparation du sous-module intégrée en étape 0 plutôt qu'en chantier séparé — sans elle
  le conftest global casse et aucun test ne peut tourner.

## Suites à donner

- **Mesure sur un run réel** — non faite : demande une `API_KEY` et un appel payant.
  Lancer la phase glossaire seule sur l'EPUB d'`examples/`, cache vidé, et comparer aux
  chiffres statiques ci-dessus.
- **Dette n°5, révélée par l'étape 0** — `TranslateParams.literary_context` porte
  désormais son type réel (`AnalyseChapter`), mais `common/literary_context_block.jinja`
  lit encore les champs plats d'`AnalyseLitteraire` : le bloc de contexte littéraire se
  rend **vide** dans les prompts des phases 1 et 2.
  `common/literary_context_layered_block.jinja` existe mais n'est branché nulle part.
  Défaut de qualité de traduction, antérieur à ce chantier, mérite son propre chantier.
- `AnalyseLitteraire` (`template/types.py`) n'a plus aucun consommateur.
