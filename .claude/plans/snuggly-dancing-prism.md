# Glossaire : format tabulaire délimité en sortie LLM

## Contexte

La phase glossaire fait produire au LLM un JSON validé par `LLMGlossaryModel`
(`src/template/phase/glossary_models.py`) via Instructor en `Mode.JSON`. Le format
est déjà tabulaire — `colonnes: tuple[4]` + `entrees: list[tuple[terme, type, sexe,
proposition]]` — mais l'enveloppe JSON coûte cher : crochets, guillemets et virgules
représentent la moitié des tokens de chaque entrée, et ces tokens-là sont des tokens
**de sortie**, les plus chers et les seuls non cacheables.

Mesure `cl100k_base` sur 5 entrées réalistes :

| Format | tok/entrée | vs actuel |
|---|---|---|
| JSON compact (actuel) | 22,4 | — |
| JSON indenté (ce que le LLM produit souvent) | 33,0 | +47 % |
| **CSV `\|`** | **12,4** | **−45 %** |

S'y ajoutent 439 tokens de schéma JSON injectés en entrée à chaque appel par
`Mode.JSON`, qui disparaissent avec la voie texte.

**Résultat attendu** : le LLM émet une ligne par terme, `terme|type|sexe|proposition`,
terminée par `[=[END]=]` — le même marqueur que les phases de traduction. Le format de
**cache** reste JSON : seul le canal LLM change, les caches existants restent lisibles.

### Blocage préalable

`master` ne s'importe pas. Le commit `43a1f6a` a déplacé le pointeur du sous-module
`src/template` de `ffab88f` vers `687aedc`, où `phase/translation_models.py` n'existe
pas. 11 fichiers `src/` et 8 fichiers de tests l'importent ; `uv run pytest` s'arrête
sur le conftest. `ffab88f` n'est sur aucune ref distante — commit perdu, le module doit
être **réécrit**. Sa spec complète subsiste : `tests/template/test_translation_models.py`
(15 tests, 109 lignes). C'est l'étape 0.

## Décisions arrêtées

- **Délimiteur `|`, sans quoting.** Le `|` n'apparaît pas en prose littéraire : pas de
  guillemets réintroduits, parsing = `split("|")` + contrôle de cardinalité.
- **Ligne malformée → rejet silencieux + WARNING.** Le glossaire est un agrégat pondéré
  sur tout le livre ; perdre un terme sur trente est sans conséquence. Zéro appel LLM
  supplémentaire, ce qui préserve le gain.
- **Périmètre glossaire seul.** `AnalyseChapter` (Phase 0) et `LineIndexedLLMResponse`
  restent inchangés.

## Hors-périmètre

- Phase 0 / `analyze_chapter_layered_models.py` — structure imbriquée, non tabulaire.
- Le format de persistance sur disque (`MemoizedChunkPersister`) — reste JSON.
- Les 6 incohérences relevées dans `glossary.py` pendant l'exploration (`save()`
  asymétrique, `_user` non normalisé, appel mort dans
  `get_translations_until_confidence`) — à traiter séparément.
- La couverture de test de `Glossary` lui-même (actuellement 15 %).

## Deux dépôts

`src/template` est un sous-module (`NeOzay/ebook-translator-template`). Les étapes 0, 1
et 2 s'y déroulent : branche + commits dans le sous-module, puis bump du pointeur côté
repo principal. Les étapes 3 à 5 sont dans le repo principal.

## Étapes

### 0. Réécrire `template/phase/translation_models.py` — déblocage

`src/template/phase/translation_models.py`, guidé test par test par
`tests/template/test_translation_models.py`. Surface à restituer :

- `type LineIndexed = dict[int, str]`
- `LineIndexedLLMResponse(ConvertibleModel[LineIndexed])` avec `lines: dict[int, str]`,
  `line_indices()`, `fragments_at(i)`, `merge(other)` (union non mutante, `other` gagne)
- un `@model_validator(mode="before")` qui accepte une `str` brute (`<N/>texte`, `</>`
  intra-ligne, `[=[END]=]` final, indices non contigus, espaces de bord tolérés) et
  laisse passer un `dict` tel quel
- erreurs levées en `PydanticCustomError(..., {"error_type": ErreursType.X, ...})`,
  reprojetées par `from_pydantic_error` (`src/ebook_translator/validation/failure.py`) :
  `MISSING_END_MARKER`, `OUTPUT_FORMAT_INVALID`, `DUPLICATE_INDICES`
  (`src/ebook_translator/validation/diagnostics.py`)

Réutiliser `ConvertibleModel` (`src/template/types.py`) — `build()`, `serialized_build()`,
`target_adapter()` sont déjà en place.

**Vérification** : `uv run pytest --no-cov` collecte et passe ; `uv run basedpyright src/`
retourne 0 erreur.

### 1. Format tabulaire dans `LLMGlossaryModel`

`src/template/phase/glossary_models.py` :

- constantes `GLOSSARY_SEPARATOR = "|"` et réutilisation du marqueur `[=[END]=]` déjà
  employé par les phases de traduction
- `@model_validator(mode="before")` acceptant `str`, sur le patron de
  `LineIndexedLLMResponse` (étape 0) : découpe en lignes, `split("|")`, `strip()`
- **la validation par ligne se fait dans le parser**, pas via les `Literal` Pydantic :
  une ligne à cardinalité ≠ 4 ou dont `type`/`sexe` sort de
  `GLOSSARY_TYPES_AUTORISES` / `GLOSSARY_SEXES_AUTORISES` est écartée, sinon une seule
  ligne fautive ferait échouer tout le chunk
- champ `lignes_rejetees: list[str]` (exclu de `build()`) pour que la phase puisse
  loguer côté `ebook_translator` ; `logging.getLogger(__name__)` en secours —
  `template/` ne doit pas dépendre de `ebook_translator`
- suppression du champ `colonnes` : l'ordre est porté par le format, et il n'est
  référencé nulle part dans `src/ebook_translator/` (vérifié)
- `entrees: list[Entree]` et ses `Literal` restent en seconde barrière pour l'entrée
  `dict` (cache, tests) ; `_build_impl()` inchangé

### 2. Réécrire la section « Format du tableau » du prompt

`src/template/phase/glossary_system.jinja` : remplacer les lignes 31-43 par la
description du format délimité, avec exemples et marqueur de fin. Corriger l'en-tête
commenté (lignes 15-18) : la structure n'est plus portée par le canal `tools`, et la
mention `Mode.TOOLS_STRICT` était déjà fausse (le client est en `Mode.JSON`,
`src/ebook_translator/llm/clients/client.py:288`).

Sortie attendue :

```
Alice|personnage|f|Alice
White Rabbit|creature|m|Lapin Blanc
Dark Army|organisation|nc|Armée des Ténèbres
[=[END]=]
```

`glossary_user.jinja` et `common/glossary_existing_block.jinja` sont inchangés.

### 3. Basculer `GlossaryPhase` sur la voie texte

`src/ebook_translator/pipeline/phases/glossary.py` : supprimer la surcharge
`get_llm_config()` (lignes 131-136). Le défaut de `PhaseBase` renvoie `self.llm`, donc
`executor.py:167` prend la branche `else` — `LLM.query()` puis
`payload_type.model_validate(llm_output)`, exactement ce que le validator de l'étape 1
rend possible. Mettre à jour la docstring du module (lignes 1-7), qui décrit la voie
Instructor. `content_checks = ()` et `persister` restent inchangés : le worker
schema-only convient toujours.

### 4. Tests et mesure du gain réel

Nouveau `tests/glossary/test_glossary_models.py` (le répertoire existe mais ne contient
aucun test) : parsing nominal, espaces de bord, `[=[END]=]` manquant, cardinalité ≠ 4,
`type`/`sexe` inconnu, ligne vide, `|` dans un terme, passthrough `dict`, `build()`.
Purger la fixture `sample_glossary` de `tests/glossary/conftest.py`, qui ne correspond
plus au format `LLMTermeGlossary`.

Puis mesurer sur un run réel contre l'EPUB d'`examples/` : comparer les tokens de sortie
avant/après sur le même livre.

### 5. Documentation

`src/template/CLAUDE.md` (bloc « Sortie LLM » ligne ~58 et l'exception
`Mode.TOOLS_STRICT` ligne 175), `docs/TEMPLATES.md`, `docs/ARCHITECTURE.md`,
`docs/CHANGELOG.md`.

## Vérification

```bash
uv run pytest --no-cov                          # vert dès l'étape 0
uv run pytest tests/glossary/ -v                # étape 4
uv run basedpyright src/                        # 0 erreur
uv run pre-commit run --all-files
```

Bout en bout : lancer `examples/example_pipeline.py` avec la seule phase glossaire sur
l'EPUB de test, cache vidé, et vérifier que les entrées arrivent bien dans le `Glossary`
et dans les Markdown `chunk N.md` du répertoire de cache.
