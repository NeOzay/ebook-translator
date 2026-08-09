# CLAUDE.md — Templates de traduction de livres

## Vue d'ensemble

Templates Jinja2 utilisés par un orchestrateur Python pour traduire des epub via l'API DeepSeek V3. Chaque phase segmente le texte, prépare les prompts system/user, appelle le modèle, valide la sortie via un pipeline de checks, et sauvegarde. En cas d'échec de check, un prompt `retry_*` ciblé est émis.

### Pipeline global

```
┌──────────────────┐
│ Analyse littér.  │─┐
│ (analyze_chapter)│ │
│ → contexte       │ │
└──────────────────┘ │    ┌─────────────┐   ┌──────────────┐
                     ├──→ │ Traduction  │ → │ Raffinement  │
┌──────────────────┐ │    │ (phase 1)   │   │ (phase 2)    │
│ Glossaire        │─┘    │ translate_  │   │ translate_   │
│ (glossary) ↻     │      │ base        │   │ refine       │
│ → entrées pondér.│      └─────────────┘   └──────────────┘
└──────────────────┘
```

Analyse littéraire et glossaire : phases **indépendantes**, parallèles (tailles de blocs différentes). Le glossaire boucle jusqu'à convergence. Les deux produits alimentent les phases de traduction.

## Architecture des templates

```
template/
├── phase/      — templates principaux (un couple system/user par type d'appel)
└── common/     — blocs réutilisables (includes)
```

**Convention** : `_system.jinja` (rôle, règles, format — invariant) / `_user.jinja` (données variables). Les `retry_*` sont des prompts de correction ciblés, émis sur échec de check.

**Variables globales** disponibles dans toute phase :

| Variable | Type | Description |
|----------|------|-------------|
| `target_language` | `str` | Langue cible (ex. `"français"`) |
| `genre` | `str` | Genre du livre, influence les consignes (défaut `"fiction"`) |

> **Convention pratique** : `target_language` vaut toujours `"français"` dans les déploiements actuels. Les exemples correct/incorrect du bloc `common_translate_rules` sont donc hard-codés en français (guillemets « … », vouvoiement, etc.). Si une autre langue cible est ajoutée, ces exemples devront être conditionnés par langue.

Chaque template déclare ses variables supplémentaires avec leur type en entête. Le même contexte est passé aux deux templates d'une paire (system/user).

## Système de balises

- `<N/>` (ex. `<0/>`, `<25/>`) : numéro de ligne. Chaque ligne traduite doit commencer par la même balise. Ordre et nombre préservés.
- `</>` : balise de formatage, remplace les vraies balises HTML. Nombre et positions relatives préservés exactement. Reconstruites en HTML après traduction.
- Lignes sans `<N/>` : contexte (non traduit, non inclus dans la sortie).
- `[=[END]=]` : marqueur de fin de sortie.

## Glossaire

Phase dédiée (pas l'analyse littéraire) pour permettre des petits blocs (extraction fine) vs grands blocs pour l'analyse.

**Sortie LLM :** tabulaire, une ligne par terme, colonnes séparées par `|`, terminée par `[=[END]=]`.

```
Dark Army|organisation|nc|Armée des Ténèbres
[=[END]=]
```

Pas d'enveloppe JSON : à structure égale, elle coûtait deux fois plus de tokens de sortie par entrée. Le `|` est choisi parce qu'il n'apparaît pas en prose littéraire — aucune règle d'échappement, donc pas de guillemets réintroduits. Parsing et tolérance dans `phase/glossary_models.py`.

**`type`** : `personnage`, `lieu`, `creature`, `appellation`, `organisation`, `objet`, `terme_technique`, `reference_culturelle`.

**Priorité en cas d'ambiguïté** (gauche prime) :
`personnage > creature > lieu > appellation > organisation > objet > terme_technique > reference_culturelle`

- Être nommé individuellement = `personnage`, pas `creature`
- Titre/surnom/rôle générique = `appellation`, pas `personnage`
- Groupe structuré (armée, guilde, faction) = `organisation`
- `reference_culturelle` = monde réel uniquement

**`sexe`** : `m`, `f`, `nc`. `m`/`f` priment sur `nc` en conflit ; entre `m` et `f`, la proposition dominante l'emporte.

### Cycle de vie

1. **Extraction** par la phase glossaire sur chaque bloc.
2. **Agrégation** Python : chaque proposition incrémente indépendamment le poids de sa `traduction`, `type`, `sexe` (trois distributions par terme).
3. **Confiance** calculée sur la distribution des traductions uniquement.
4. **Réinjection** selon règles par phase (voir plus bas).

La classe `Glossary` conserve **toutes** les propositions avec leurs poids, sans seuil. Les seuils sont des **politiques de lecture**, pas de stockage. Export/import possible pour reprise de convergence ou partage entre livres.

### Niveaux de confiance

| Niveau | Score | Signification |
|--------|-------|---------------|
| `high` | ≥ 0.7 | Stable, converge |
| `medium` | ≥ 0.6 | Dominante probable, arbitrage possible |
| `low` | < 0.6 | Conflit ou signal faible |

**Formule** (sur la distribution des traductions) :
```python
def compute_confidence(d: list[int]) -> float:
    total = sum(d)
    ratio = max(d) / total
    dominance = math.pow(ratio, 0.5)
    masse = total / (total + 2)  # k=2
    return round(dominance * masse, 2)
```

`masse` pénalise les faibles volumes : une unanimité aveugle ne produit pas de `high` tant que le poids total reste bas.

**Sélection des propositions affichées** : ajoutées par poids décroissant jusqu'à ce que le score de couverture atteigne le seuil. Même logique pour `types` et `sexes`.

### Règles d'injection par phase

**Phase glossaire** — via `glossary_existing_block.jinja` :
- Sélection : terme présent dans le bloc courant. **Aucun filtre de poids** : un terme trop léger pour être arbitré doit quand même être vu, sinon le LLM le réémet sous une forme voisine et divise d'autant son poids.
- `weight ≥ 3` (`DEFAULT_MIN_REINJECTION_WEIGHT`) ne filtre pas, il décide de l'**affichage** : au-delà les propositions pondérées sont montrées, en deçà la seule forme du terme.
- Trois groupes : `high` en contexte compact (exclu de la sortie LLM), le reste en propositions pondérées ou en forme seule.
- Borne : `DEFAULT_MAX_REINJECTED_TERMS` (80) plafonne le bloc. Ne mord pas sur un run normal (54 termes/bloc au plus, mesuré sur un tome complet) ; existe pour le glossaire prérempli. Quand il mord, garde `arbitrer` > `emergent` > `valide`.

**Phases 1/2** — via `glossary_block.jinja` :
- Filtre : dominance ≥ 0,95 sur la distribution des traductions, ou confiance non-`low`.
- Plafond : `glossary_max_terms` (25 par défaut), trié par occurrences dans le chunk puis poids.

⚠️ Le filtre de dominance laisse passer **presque tout** : un terme vu une seule fois a une dominance de 1,0. Mesuré sur un tome réel (329 termes appris), **319 passent** — dont 218 de poids 1. Ce n'est donc pas la dominance qui protège les phases de traduction du bruit, c'est le plafond de 25 et son tri. Une entrée du glossaire vue une fois vaut, pour le prompt de traduction, une entrée convergée.

### Structures Python

`GlossaryEntry` — entrée **résolue** (valeurs uniques) pour phases 1/2 via `glossary_block.jinja` :
- `terme`, `traduction`, `type`, `sexe`, `confidence`
- `weight` optionnel (absent pour termes user)

`GlossaryMultipleValueEntry` — **multi-propositions pondérées** pour phase glossaire via `glossary_existing_block.jinja` :
- `terme`, `weight`, `confidence`
- `traductions`, `sexes`, `types` : `list[tuple[str, int]]` triées par poids décroissant

**Distinction des deux blocs** : `glossary_block.jinja` (résolu, phases 1/2) vs `glossary_existing_block.jinja` (multi-propositions, phase glossaire).

## Contexte littéraire

Produit par `analyze_chapter_system.jinja`, injecté dans les phases 1/2 via `literary_context_block.jinja`. Contient : résumé narratif, tonalité, style, thèmes, références culturelles, pistes de traduction.

## Retry et checks

Chaque sortie LLM passe par un pipeline de checks (Python). Sur échec, un `retry_*` produit un prompt de correction ciblé.

| Template | Déclenché quand |
|----------|-----------------|
| `retry_correct_fragments_system` | Nombre de `</>` incorrect (modes `strict`/`flexible`) |
| `retry_correct_punctuation_system` | Incohérence de ponctuation |
| `retry_translate_missing_lines_targeted_system` | Lignes `<N/>` manquantes |
| `retry_translate_sentence_system` | Phrase à retraduire |
| `retry_correct_analysis_invalid_json_system` | JSON contexte littéraire invalide |
| `retry_correct_analysis_missing_sections_system` | Sections obligatoires manquantes |

Les retry de traduction utilisent `common_translate_rules_light.jinja` (sans les exemples) : le modèle a déjà vu les règles complètes au premier appel.

## Principes de rédaction des prompts

**Faire** :
- Ton neutre et déclaratif ("La sortie doit contenir exactement 3 `</>`")
- Règles déclaratives, pas impératives
- Séparer règles invariantes (system) / données variables (user)
- Une seule occurrence de chaque règle
- Règles avant données
- Exemples concrets correct/incorrect
- Contraintes de format explicites ("Commence par `{`", "termine par `[=[END]=]`")

**Éviter** :
- Emojis dans les titres (tokens sans signal)
- Séparateurs `---` (un `###` suffit)
- Ton punitif (bruit sans effet)
- Explications du "pourquoi" des instructions
- Répétition de règles pour "insister"
- Numérotation bancale (`règle 2.5`, `règle 3bis`)

**Économie de tokens** : retry en version `light`, format tabulaire délimité pour le glossaire, `nc` (2 tokens) au lieu de `non_concerne`.

**Exception — phases JSON outillées par Pydantic + Instructor** : pour ces phases (`analyze_chapter_layered` seule aujourd'hui), la structure JSON est portée par l'API et la source de vérité est le modèle Pydantic dans `phase/<phase>_models.py`. Les consignes type "Commence par `{`", "termine par `}`", la section "Structure JSON attendue" et la description textuelle des champs **disparaissent du prompt**. Restent dans le prompt les contraintes non exprimables en schéma : règles d'arbitrage, de catégorisation, exemples.

Le glossaire est repassé en voie texte (format tabulaire, cf. plus haut) : sa structure n'étant plus portée par aucun schéma transmis à l'API, elle **doit** être décrite dans `glossary_system.jinja`, en restant synchronisée avec `GLOSSARY_COLUMNS` et `GLOSSARY_SEPARATOR`. Les autres phases (traduction, retries texte) suivent la règle générale ci-dessus.

## Graphe de dépendances

```
translate_base_system / translate_refine_system
  ├── common_translate_rules
  ├── glossary_block
  └── literary_context_block

retry_correct_fragments_system         [mode: "strict" | "flexible"]
retry_correct_punctuation_system
  └── common_correct_rules

retry_translate_missing_lines_targeted_system
retry_translate_sentence_system
  └── common_translate_rules_light

retry_correct_analysis_*_system        (aucun include)

analyze_chapter_system                 [existing_analysis: bool — mode incrémental]
  (aucun include)

glossary_system
  └── glossary_existing_block
```

Seuls les `_system.jinja` sont listés : les `_user.jinja` ne font pas d'include. Avant de modifier un include partagé : vérifier tous ses consommateurs (contradiction possible).
