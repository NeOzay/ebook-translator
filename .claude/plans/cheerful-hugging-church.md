# Préremplissage du glossaire (`glossary-seeding`)

## Context

La phase glossaire n'a été éprouvée que sur un livre court (*The Yellow Wallpaper*). Or la mécanique
de convergence est dimensionnée par le facteur de masse `w / (w + 2)` : il faut **5 émissions**
unanimes pour qu'un terme atteigne la confiance haute, et **3** pour qu'il soit réinjecté avec ses
propositions. Sur un livre trop court, aucun terme ne converge — les mécanismes de sélection ne sont
tout simplement pas exercés.

Mesures sur un glossaire réel de livre long (`books/.Chillin' … Volume 02 …_glossary.json`, 329 termes)
confirment que le régime y est très différent :

| Mesure | Valeur |
| --- | --- |
| Confiance `high` / `medium` / `low` | 37 / 23 / 269 |
| Poids médian | 1 (218 termes vus une seule fois) |
| Termes retenus par `get_translation` (→ prompts phases 1/2) | 319 / 329 |

Attendre qu'un run complet sur un livre de 20 Mo produise ces états coûte cher et ne permet pas de
cibler un cas précis. **Préremplir le glossaire** donne le contrôle : on place chaque terme dans
l'état voulu et on observe la réaction du modèle en un seul chunk.

**Résultat visé** : pouvoir écrire un fichier de seed déclaratif, l'injecter dans un pipeline ou une
variante de banc, et lancer un run dont le comportement de sélection est observable et reproductible.

## Périmètre

**But** — outiller le préremplissage du glossaire et lever les deux défauts qui l'empêchent de
fonctionner sur livre long.

**Critères de réussite**
- Un fichier de seed TOML produit un `Glossary` dont les termes tombent dans les trois groupes
  attendus de `glossary_existing_block.jinja` (validés / à arbitrer / émergents), vérifié par le
  prompt rendu.
- Une entrée `user` préremplie est effectivement retrouvée dans le texte et exclue des entrées
  apprises (aujourd'hui elle ne l'est pas — bug de casse).
- Un run de banc sur un livre long démarre avec un glossaire seedé et produit un audit exploitable.

**Hors-périmètre** (à valider)
- Le filtre `dominance ≥ 0.95` de `get_translation`, qui laisse passer 97 % des termes vers les
  prompts de traduction. C'est un **objet de mesure** de ce chantier, pas une cible de correction :
  on ne change pas la politique de sélection avant de l'avoir observée.
- Le tri de `collect_entry` (occurrences dans le chunk avant fiabilité).
- La piste de cache « bloc validés append-only » discutée en amont — dépend des résultats.
- Toute refonte de `glossary_system.jinja`.

## Étapes

### 1. Corriger la casse des entrées `user`

`Glossary.add_user_translation` (`src/ebook_translator/glossary.py:375`) stocke la clé brute
(`self._user[terme]`) alors que toutes les lectures comparent en minuscules :
`collect_entry` teste `terme in text` sur un texte déjà `lower()`, et les deux collecteurs excluent
les apprises par `if terme_lower in self._user`. Une entrée `"Matrix"` n'est donc ni retrouvée ni
exclue.

Corriger en normalisant la clé (`self._user[terme.lower()]`, cohérent avec le champ `terme` du
`GlossaryEntry` construit juste au-dessus, déjà en minuscules). Aucun appelant dans `src/` — le
risque de régression est nul. Vérifier aussi `import_from_volume` (`glossary.py:686`), qui recopie
les clés `user` d'un JSON tel quel : normaliser à l'import également.

Tests : `tests/glossary/test_seeding.py` (nouveau) — une entrée user en casse mixte est collectée par
`collect_entry`, et le terme appris homonyme n'apparaît pas en double.

### 2. Module de seed déclaratif

Nouveau `src/ebook_translator/glossary_seed.py`. Format TOML (lu par `tomllib`, stdlib), où l'on
écrit l'**intention** plutôt que le poids — les trois niveaux correspondent exactement aux trois
groupes du prompt :

```toml
[[terme]]
terme = "rick gladiolus"
traduction = "Rick Gladiolus"
type = "personnage"
sexe = "m"
niveau = "valide"          # poids unanime = converged_weight() → confiance high

[[terme]]
terme = "nursery"
type = "lieu"
sexe = "f"
niveau = "arbitrer"        # conflit fabriqué, poids total >= DEFAULT_MIN_REINJECTION_WEIGHT
propositions = [["la nursery", 3], ["la chambre d'enfants", 2]]

[[terme]]
terme = "yellow wallpaper"
traduction = "le papier peint jaune"
type = "objet"
sexe = "nc"
niveau = "emergent"        # poids 1

[[terme]]
terme = "matrix"
traduction = "Matrice"
type = "terme_technique"
sexe = "f"
user = true                # entrée validée, priorité absolue
```

Le chargeur réutilise les primitives existantes plutôt que d'écrire dans `_glossary` :
- `niveau = "valide"` → `converged_weight()` (`glossary.py:130`) appels à `learn()` ;
- `niveau = "arbitrer"` → un `learn()` par unité de poids de chaque proposition ;
- `niveau = "emergent"` → un seul `learn()` ;
- `user = true` → `add_user_translation()`.

Passer par `learn()` garantit que les distributions, les graphies (`translation_casing`) et le cache
d'entrées restent cohérents, et que le seed vieillit avec le format. `propositions` explicite prime
sur `traduction` + `niveau`.

API : `load_seed(path: Path) -> Glossary` et `apply_seed(glossary: Glossary, path: Path) -> None`,
pour pouvoir seeder aussi bien un glossaire neuf qu'un glossaire importé d'un tome précédent.
Erreurs de format : `ValueError` explicite (terme manquant, `niveau` inconnu, `type`/`sexe` hors des
valeurs de `GlossaryEntryType` / `GlossaryEntrySexe`).

Tests : chaque niveau atterrit dans le bon groupe du prompt rendu — même approche que
`tests/glossary/test_reinjection.py`, qui rend le prompt via `TemplateRenderer().render_prompt` et
découpe sur les en-têtes de section. C'est la vérification qui compte : elle porte sur ce que le
modèle voit, pas sur l'état interne.

### 3. Plafonner `collect_entry_with_conflicts`

`collect_entry_with_conflicts` (`glossary.py:454`) n'a pas d'équivalent du `max_terms=25` de
`collect_entry` : tous les termes appris présents dans le bloc partent dans le prompt système. Avec
un glossaire seedé de plusieurs centaines de termes, le bloc « Glossaire existant » enfle sans borne,
et il n'est pas cachable (son contenu dépend du chunk).

Son docstring précise que l'absence de **filtre de poids** est délibérée — un terme léger doit rester
visible sinon le modèle le réémet sous une variante. Un plafond n'est pas un filtre de poids : il ne
mord qu'au-delà d'un volume que le livre court n'atteint jamais. Ajouter `max_terms: int = 80`, tri
par occurrences dans le bloc puis poids (même clé que `collect_entry:450`, pour une seule politique
de troncature dans le module). Documenter dans le docstring que le plafond est une borne de prompt,
pas un jugement de pertinence.

Tests : au-delà du plafond la troncature garde les plus présents ; en deçà le comportement actuel est
inchangé (les tests de `test_reinjection.py` doivent passer sans modification).

### 4. Câblage builder et banc

`PipelineBuilder.glossary()` (`pipeline/builder.py:439`) accepte déjà une instance préconfigurée —
le canal existe. Ajouter le sucre `PipelineBuilder.glossary_seed(path)` qui construit le `Glossary`
via `load_seed`, pour qu'une config de banc reste déclarative.

Point de vigilance à traiter : `Pipeline._glossary_export_path` (`pipeline/pipeline.py:138`) protège
la source en lecture seule via `Glossary.cache_path`. Un glossaire construit par seed a
`cache_path = None` et n'est donc pas protégé — le run exportera vers `.<stem>_glossary.json` et
pourra écraser un glossaire existant du même livre. Sur le banc, `RunEnv` isole chaque variante, mais
hors banc le risque est réel : vérifier le comportement et, si besoin, faire porter au glossaire
seedé le chemin du fichier de seed comme source à ne pas écraser.

Livrable : `bench/config_glossaire_seed.py`, sur le modèle de `bench/config_exemple.py` — deux
variantes sur un livre long (`books/Chillin' … Volume 01`), l'une seedée depuis le glossaire du
tome 2 déjà disponible, l'autre à froid, avec l'analyse littéraire figée par le run d'amorçage.

### 5. Documentation

- `docs/ARCHITECTURE.md` ou une section de `docs/BENCH.md` : le format de seed et son usage.
- `src/template/CLAUDE.md` : la section « Règles d'injection par phase » décrit le filtre des phases
  1/2 comme « dominance totale ». C'est exact à la lettre mais trompeur en pratique — un terme vu une
  seule fois a une dominance de 1,0 et passe. Corriger la formulation et donner le chiffre mesuré.

### 6. Run et audit

Lancer le banc de l'étape 4, puis `uv run ebook-audit` sur la phase glossaire de chaque variante, et
faire trancher par `/phase-audit`. C'est ce run qui doit dire si le filtre `dominance ≥ 0.95` et le
tri de `collect_entry` méritent le chantier suivant.

## Vérification

```bash
uv run pytest tests/glossary/ --no-cov -v      # étapes 1-3
uv run basedpyright src/                        # doit rester à 0 erreur
uv run pre-commit run --all-files
uv run ebook-bench bench/config_glossaire_seed.py   # étape 6, run réel (coût API)
```

Le test qui fait foi pour les étapes 1-3 est celui qui rend le prompt système de la phase glossaire à
partir d'un seed et vérifie la répartition en trois groupes : il porte sur ce que le modèle reçoit.

## Suivi

Chantier suivi dans `.claude/implementation/glossary-seeding.md`, sur la branche `glossary-seeding`
issue de `master`.
