# Migration des prompts JSON vers Pydantic + Instructor

Guide conceptuel destiné à servir de point de départ à une nouvelle conversation.

## Contexte

Les phases produisant du JSON (`glossary`, `analyze_chapter_layered`) reposent aujourd'hui sur :

- une description textuelle du format dans le `_system.jinja`,
- une validation et des corrections gérées côté orchestrateur via des prompts `retry_*` dédiés,
- une synchronisation manuelle entre la structure du JSON décrite dans le prompt et les checks Python.

Toute évolution de la structure JSON impose de mettre à jour en cohérence : le prompt, les checks, les retries. La maintenance est fastidieuse et fragile.

## Objectif

Faire de **Pydantic la source de vérité unique** de la structure JSON, et déléguer à **Instructor** la conversion modèle → schéma envoyé au LLM ainsi que la boucle de validation/retry.

## Prérequis techniques et état actuel

Ce guide est une **proposition de migration** ; il ne décrit pas l'état courant du projet.

| Élément | État actuel | Cible du guide |
|---|---|---|
| API DeepSeek | V3 (`deepseek-chat`) | V4 (`deepseek-v4-flash` par défaut, basculable sur `deepseek-v4-pro`) |
| Mode tools strict | Indisponible en V3 | Disponible en V4 ; prérequis dur de cette migration |
| Validation JSON | Checks Python ad-hoc + retries dédiés | Pydantic + boucle Instructor |
| Tracabilité | Existante côté orchestrateur | Réutilisée via hooks Instructor |

**Conditions de bascule** (à vérifier avant de démarrer) :

- Disponibilité confirmée de `deepseek-v4-flash` et du `Mode.TOOLS_STRICT` côté API DeepSeek.
- Tarification et quotas V4 acceptables vs. V3 sur le volume cible.
- Tests de non-régression sur un échantillon représentatif de chapitres avant bascule générale.

**Versions logicielles minimales :**

- **Pydantic ≥ 2.x.** Le guide utilise les API v2 : `pydantic.ConfigDict`, `pydantic.Field`, le décorateur `@field_validator` (et non `@validator` v1), `model_dump_json()` (et non `json()` v1). Une migration depuis Pydantic v1 préalable est nécessaire si la base de code n'est pas déjà sur v2.
- **Instructor ≥ version exposant `Mode.TOOLS_STRICT`.** À ce jour, ce mode est récent ; vérifier le changelog d'Instructor à l'instant de la migration et figer la version dans le `pyproject.toml` / équivalent.
- **Client OpenAI Python ≥ 1.x** (le client `openai` v1, sur lequel Instructor se branche).

Imports attendus (référence) :

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal
import instructor
from openai import OpenAI
```

Si la base de code utilise encore Pydantic v1, ce guide ne s'applique **pas tel quel** : adapter d'abord la base à v2 ou transposer les API (`@validator` → `@field_validator`, `Config` interne → `model_config = ConfigDict(...)`, `.json()` → `.model_dump_json()`, etc.).

## Décisions retenues

| Aspect | Décision |
|---|---|
| Validation structurelle | Pydantic v2 |
| Couche LLM | Instructor sur client OpenAI-compatible (DeepSeek V4 — cible de migration, voir « Prérequis ») |
| Mode Instructor | `Mode.TOOLS_STRICT` |
| Modèle DeepSeek par défaut | `deepseek-v4-flash` (configurable, sans thinking) |
| Mode thinking | Désactivé sur ces phases (incompatible `TOOLS_STRICT`) |
| Localisation des modèles Pydantic | Co-localisés dans `phase/`, suffixe `_models.py` |
| Format du glossaire (`colonnes` / `entrees`) | Conservé tel quel pour économie de tokens |
| Logique d'arbitrage (priorités, conflits) | Reste dans l'orchestrateur, pas encodée en validators |
| Validators Pydantic | Limités à la validité des valeurs (enums, longueurs, formats) |
| Templates `retry_correct_analysis_*` | Hors périmètre de ce guide |
| Stratégie | Phase par phase, **glossary d'abord**, puis `analyze_chapter_layered` |
| Tracabilité | Écriture brute dans un descripteur de fichier fourni par l'orchestrateur |

## Architecture cible

### Ce qui disparaît

- La section "**Structure JSON attendue**" des `_system.jinja`.
- La section "**Format de sortie**" indiquant `Commence par {`, `termine par }`, etc.
- La description textuelle des enums et des contraintes de longueur, lorsqu'elle est exprimable en types Python.
- Les checks Python ad-hoc qui dupliquent la structure attendue.
- Les templates `retry_correct_analysis_invalid_json_*` et `retry_correct_analysis_missing_sections_*` (hors périmètre du guide, mais à supprimer en pratique).

> **Exception explicite au `CLAUDE.md`.** La section *Principes de rédaction des prompts* du `CLAUDE.md` recommande d'inclure des contraintes de format explicites (`Commence par {`, `termine par [=[END]=]`). Cette consigne **reste valable pour toutes les phases qui ne sont pas outillées par Instructor + `TOOLS_STRICT`** (notamment la traduction, qui produit du texte annoté). Pour les seules phases JSON migrées selon ce guide, la contrainte de format est portée par le canal `tools` de l'API et son rappel textuel devient redondant. À documenter en parallèle dans le `CLAUDE.md` (section principes) sous forme de note d'exception, pour éviter une consigne contradictoire entre les deux documents.

### Ce qui apparaît

- Un fichier `<phase>_models.py` à côté de chaque paire `<phase>_system.jinja` / `<phase>_user.jinja`.
- Un `BaseModel` racine par phase, exposant la structure attendue.
- Des `Field(description=...)` qui portent les contraintes sémantiques par champ.
- Des `@field_validator` ciblés sur la **validité des valeurs** (pas sur l'arbitrage métier).
- Un appel Instructor en `Mode.TOOLS_STRICT` côté orchestrateur, avec hooks de log branchés sur le file descriptor de trace.

### Ce qui ne change pas

- Le rendu Jinja des prompts (mêmes mécanismes d'inclusion, mêmes variables globales).
- Les phases de **traduction** (`translate_base`, `translate_refine`) et leurs retries — elles ne produisent pas de JSON.
- Le pipeline d'agrégation et d'arbitrage du glossaire côté orchestrateur.
- Le découpage `_system.jinja` / `_user.jinja` (rôle/règles invariantes vs. données variables).

## Conventions de co-localisation

```
phase/
├── glossary_system.jinja
├── glossary_user.jinja
├── glossary_models.py                       ← BaseModel + validators + enums
├── analyze_chapter_layered_system.jinja
├── analyze_chapter_layered_user.jinja
└── analyze_chapter_layered_models.py
```

**Règles :**

- Un fichier `_models.py` par phase JSON, même nom de base que la paire de templates.
- Un seul `BaseModel` racine exposé par fichier (autres modèles internes au besoin).
- Les enums (`Literal[...]` ou `enum.StrEnum`) **vivent à côté du modèle qui les utilise**, pas dans un `types.py` global. Si une enum est partagée entre phases, la promouvoir dans `types.py` racine.

## Mapping prompt → schéma

La règle d'or : tout ce qui est exprimable en types Python migre dans le modèle Pydantic, le reste reste dans le prompt.

### Migre dans Pydantic

| Élément du prompt actuel | Forme Pydantic |
|---|---|
| Description structurelle (champs, imbrication) | Hiérarchie de `BaseModel` |
| Enum de valeurs autorisées (`type` du glossaire, `signal_cloture`) | `Literal[...]` ou `StrEnum` |
| Longueur min/max d'une chaîne ou d'une liste | `Field(min_length=, max_length=)` |
| Contrainte numérique (≥ 0, etc.) | `Field(ge=, le=)` |
| Cardinalité d'une liste | `Field(min_length=, max_length=)` |
| "Commence par `{`, termine par `}`" | Implicite : Instructor force la structure |
| "Tous les champs remplis, même par valeur courte" | Aucun champ optionnel + `min_length=1` |
| Description sémantique d'un champ | `Field(description="...")` |
| Description du rôle du modèle (classe entière) | docstring de la classe |

### Reste dans le prompt

- **Rôle** et cadrage métier (`Tu es un expert en …`).
- **Principes éditoriaux** (synthétique, factuel, utile à la traduction).
- **Conventions du pipeline** (balises `<N/>`, `[=[END]=]`, etc. — peu pertinent ici, plus pour la traduction).
- **Logique conditionnelle** (modes `bootstrap` / `seed` / `incremental`, `is_last_block`).
- **Règles d'arbitrage et de priorité** (priorité des `type`, gestion des conflits `m`/`f`/`nc`) — par décision, l'arbitrage reste dans l'orchestrateur, donc le prompt continue de guider le LLM en langue naturelle vers le bon choix initial.
- **Budgets descriptifs non exprimables** ("max 8 lignes", "1 à 2 phrases") — soit on accepte qu'ils restent indicatifs dans le prompt, soit on les approxime via `max_length` en caractères, à arbitrer.
- **Contexte injecté** (chapitre, glossaire existant, analyse précédente).

### Anti-pattern : la double déclaration

Une fois la structure migrée dans Pydantic, **ne pas la redécrire dans le prompt**. Le LLM voit le schéma via le canal `tools` de l'API ; le redondre dans le texte gaspille des tokens et risque la contradiction lors d'une évolution.

Cas particulier : si une contrainte exprimée dans le schéma est contre-intuitive (un enum à valeurs rares, par exemple), un **rappel court avec exemple** dans le prompt peut aider — à mesurer.

## Pattern : chain-of-thought via l'ordre des champs

Recommandé par la doc Instructor (`concepts/prompting`). Principe : un LLM auto-régressif génère les champs d'un objet structuré **dans l'ordre de leur déclaration**. Placer un champ de raisonnement **avant** un champ de décision force le modèle à expliciter sa réflexion avant de fixer la valeur finale — un chain-of-thought structurel, sans toucher au prompt.

### Forme canonique

```python
class Decision(BaseModel):
    raisonnement: str = Field(
        description="Raisonnement étape par étape qui justifie le choix ci-dessous"
    )
    valeur: Literal["a", "b", "c"]
```

Le LLM doit produire `raisonnement` avant de pouvoir produire `valeur` ; il "pense" donc explicitement avant de choisir.

### Recommandations de la doc Instructor

- **Localiser, ne pas globaliser** : ajouter un champ de raisonnement **dans le sous-modèle concerné** plutôt qu'un seul champ `chain_of_thought` global au niveau racine. Plus le raisonnement est ciblé, plus il est utile.
- **Décrire le raisonnement attendu** dans le `description=` du `Field` : "Pas à pas, en citant les indices du texte" oriente bien mieux qu'un simple "raisonnement".
- **Réserver aux décisions non triviales** : sur un champ obvie (`titre: str`), un CoT est du gaspillage de tokens. Cibler les choix d'enum, les arbitrages, les révisions conditionnelles.

### Trade-off à arbitrer

Un champ CoT ajoute des tokens **en sortie**, donc du coût et de la latence. À évaluer sur chaque cas : un CoT sur un sous-modèle répété N fois (ex. chaque arc d'`arcs_en_cours`) multiplie l'inflation.

Règle pratique : ajouter un CoT là où, sans lui, on observe une dérive ou un mauvais choix — pas par principe.

### Application possible aux phases du projet

Ces propositions sont **conceptuelles**, à valider par mesure avant adoption.

**Glossaire** — la décision sensible est le `type` (priorité d'arbitrage complexe). Le format `colonnes` / `entrees` impose des chaînes plates par entrée, donc pas d'imbrication d'objet possible. Deux options :

- **Pas de CoT structurel sur le glossaire.** Le format actuel privilégie l'économie de tokens ; ajouter du raisonnement par entrée romprait l'invariant. Préférer continuer à guider le `type` via les règles du prompt.
- **CoT global au niveau du bloc**, hors du tableau : un champ `analyse_extraction: str` placé **avant** `glossaire` au niveau racine, qui formule en une ligne la lecture du bloc avant l'extraction. À mesurer si ça améliore la précision des `type` ; à abandonner sinon.

**`analyze_chapter_layered`** — plusieurs candidats :

- Sur chaque entrée d'`arcs_en_cours`, placer `raisonnement_signal_cloture: str` **avant** `signal_cloture`. La sémantique de l'enum (`aucun` / `resolution_explicite` / `ambigu`) repose sur une lecture fine du texte ; un raisonnement court peut stabiliser le choix. Coût : un CoT par arc (à plafonner si la liste s'allonge).
- En mode `incremental`, ajouter au niveau de `NoyauStable` un champ `decision_revision: str` **avant** les champs effectivement modifiés, décrivant si une révision est nécessaire et pourquoi. Substitue partiellement la consigne textuelle "ne modifie ses champs que sur évolution notable ou contradiction explicite" en la rendant **observable et auditable** dans la sortie. Coût modéré (un seul champ).
- En mode `seed`, idem côté `couche_narrative` : `decision_amorce: str` avant le résumé, pour expliciter ce qui est repris du chapitre précédent et ce qui est introduit.

### Conséquence pour la rédaction des prompts

Un CoT structurel dans le modèle **dispense d'écrire les mêmes consignes en prose** dans le prompt :

- Avant : "Avant de modifier le `noyau_stable`, vérifie qu'il y a un changement notable et explique-le."
- Après : un champ `decision_revision: str = Field(description="Indique si le noyau évolue, et en citant le passage qui le justifie")` placé avant les champs concernés.

C'est une autre forme du déplacement prompt → schéma : **non plus déplacer la *structure*, mais déplacer la *séquence de raisonnement* attendue**.

### Conséquence pour la trace

Les CoT sont écrits dans la trace comme n'importe quel champ. Avantage : on peut **auditer a posteriori** pourquoi le LLM a fait tel choix (très utile pour le debug d'arbitrage du glossaire ou de stabilité du noyau). À documenter dans la convention de trace si on adopte le pattern.

## Cas spécifique : format `colonnes` / `entrees` du glossaire

Décision : **conserver le format actuel**. Le strict mode l'accepte (c'est du JSON Schema valide), mais ne contraint pas la structure interne des sous-listes (toutes typées `str`). Les contraintes "exactement 4 chaînes par entrée, dans cet ordre, valeurs `type`/`sexe` valides" sont à porter par des `@field_validator`.

**Conséquences pour la rédaction du prompt :**

- Le schéma n'apprend pas seul au LLM que `entrees[i][1]` doit être un type valide. Il faut **documenter le format dans le prompt**.
- Recommandation : conserver dans le prompt
  - la liste des colonnes attendues, dans l'ordre,
  - la liste des valeurs autorisées pour `type` et pour `sexe`,
  - un ou deux exemples d'entrée bien formée.
- Les `@field_validator` de Pydantic **rattrapent** les écarts en réinjectant la `ValidationError` au LLM via Instructor.

**Conséquences pour le modèle Pydantic :**

- Le modèle racine expose `colonnes: list[Literal[...]]` (ordre fixe, longueur fixe) et `entrees: list[list[str]]`.
- Un validator vérifie que chaque sous-liste a 4 éléments.
- Un validator vérifie que les valeurs des positions 1 (`type`) et 2 (`sexe`) appartiennent aux ensembles autorisés.
- Les messages d'erreur des validators doivent être **directement actionnables par le LLM** : citer la position de l'entrée fautive, la valeur reçue, les valeurs autorisées.

C'est sur ce point que la qualité de la rédaction des messages de validators pèse le plus : ils deviennent des micro-prompts de correction.

## Cas spécifique : `analyze_chapter_layered`

La phase est une **analyse incrémentale par blocs** (≈ 5000 tokens) avec trois modes (`bootstrap`, `seed`, `incremental`) et un drapeau `is_last_block`. Le snapshot d'un bloc est consommé par la traduction du bloc correspondant ; la fiche finale d'un chapitre amorce le chapitre suivant.

**Conséquences pour la migration :**

- **Un seul modèle Pydantic** pour les 3 modes : la structure JSON de sortie est identique, seules les règles de mise à jour diffèrent.
- Les **trois modes restent du ressort du prompt** : ce sont des règles éditoriales sur ce que le LLM doit faire avec les champs, pas des structures différentes.
- Le drapeau `is_last_block` reste également dans le prompt — il déclenche des consignes de clôture, pas un changement de schéma.
- Les **snapshots intermédiaires** échangés entre l'orchestrateur et le LLM (entrée `existing_analysis`, entrée `previous_chapter_analysis`) sont sérialisés depuis ce même `BaseModel`. Côté Python : `model_dump_json()` pour produire l'entrée, parsing libre pour la lire.
- Les **budgets par champ** ("`resume_narratif` max 8 lignes", "`pistes_traduction` max 15 entrées") :
  - les budgets exprimables en cardinalité de liste passent en `Field(max_length=...)`,
  - les budgets en lignes/phrases restent indicatifs dans le prompt.
- Le filtrage des arcs `resolution_explicite` côté Python (mentionné dans le `_system.jinja`) reste côté orchestrateur, en dehors du modèle.

## Modèle DeepSeek et configuration Instructor

- **API cible** : DeepSeek V4 (cf. section « Prérequis »). L'orchestrateur cible aujourd'hui V3 ; cette migration suppose la bascule préalable.
- **Client** : OpenAI-compatible, base URL DeepSeek, modèle `deepseek-v4-flash` par défaut (paramètre de l'orchestrateur, facilement basculable vers `deepseek-v4-pro`).
- **Mode Instructor** : `Mode.TOOLS_STRICT`. Le serveur force la conformité au schéma au décodage : les erreurs structurelles (champ manquant, mauvais type, hors enum) sont éliminées côté API.
- **Thinking** : désactivé sur ces phases. Le strict mode l'exclut. Les phases d'analyse et de glossaire sont exécutées sans thinking ; à mesurer si une dégradation qualitative se manifeste.
- **`max_retries`** : nécessaire malgré le strict mode, pour rattraper les violations de validators custom (longueurs hors limites, valeurs invalides dans les sous-listes du glossaire). Une valeur initiale de `2` ou `3` est raisonnable.

### Contraintes induites par `TOOLS_STRICT` sur les modèles Pydantic

À garder en tête lors de la rédaction des `_models.py` :

- `model_config = ConfigDict(extra="forbid")` sur tous les `BaseModel`.
- Tous les champs **présents dans le schéma** doivent être `required`. Les vrais optionnels passent par `Optional[T]` avec `None` explicitement autorisé dans le schéma.
- Pas d'`Union` libre complexe ; préférer des **discriminated unions** (`Field(discriminator=...)`) si nécessaire.
- Pas de schémas auto-référents profonds.
- Les validators custom n'altèrent pas le schéma transmis au LLM ; ils n'agissent qu'en post-réception. Leur unique levier sur le LLM est le **message d'erreur** qu'ils renvoient via la boucle de retry d'Instructor.

## Tracabilité

Contrainte du projet : tout appel LLM doit être tracé (prompt envoyé + réponse reçue). Approche retenue, simple :

- L'orchestrateur ouvre (ou reçoit) un descripteur de fichier dédié à la trace.
- Les hooks Instructor `completion:kwargs` (avant l'appel API) et `completion:response` (après) écrivent **directement** dans ce descripteur.
- Format libre, mais à la rédaction inclure : un identifiant de corrélation (pour relier les tours d'une même boucle de retry), un horodatage, le nom de la phase, le mode (`bootstrap`/`seed`/`incremental` pour l'analyse), les `messages` envoyés, la réponse brute.

**Implication structurante** : un appel logique côté orchestrateur peut produire **N entrées de trace** côté LLM si la boucle de retry s'enclenche. C'est attendu, et le `correlation_id` permet de regrouper.

À documenter à proximité du code : un appel LLM = au moins 1 entrée, potentiellement 1 + `max_retries` entrées en cas d'échecs successifs.

## Plan de migration phase par phase

### Phase 1 : `glossary` (en premier)

Justifications du choix : single-shot, schéma plat (pas d'imbrication multi-niveaux), permet d'éprouver la chaîne complète (Pydantic + Instructor + tracabilité + DeepSeek V4) sur le cas le plus simple.

Étapes conceptuelles :

1. Définir `phase/glossary_models.py` :
   - enums `TypeGlossaire`, `Sexe` (ou `Literal[...]`),
   - modèle racine `GlossaireResponse` enveloppant `glossaire: GlossaireBlock`,
   - validators sur `entrees` (longueur 4, valeurs de `type`/`sexe`).
2. Réécrire `phase/glossary_system.jinja` :
   - retirer "Structure JSON attendue",
   - retirer "Format de sortie",
   - conserver le rôle, les consignes, la liste des colonnes, les valeurs autorisées pour `type`/`sexe`, les exemples d'entrées bien formées (le format `colonnes`/`entrees` n'est pas porté par le schéma seul).
3. Côté orchestrateur : remplacer l'appel + checks par un appel Instructor `Mode.TOOLS_STRICT` avec `response_model=GlossaireResponse` et hooks de trace.
4. Vérifier que la consommation aval (agrégation, arbitrage) accepte une instance `GlossaireResponse` en entrée — éventuellement par `model_dump()` si l'aval reste basé sur des dict.
5. Tester sur un échantillon de blocs représentatifs, mesurer le taux de retry.

### Phase 2 : `analyze_chapter_layered`

Étapes conceptuelles :

1. Définir `phase/analyze_chapter_layered_models.py` :
   - enum `SignalCloture` (`aucun`, `resolution_explicite`, `ambigu`),
   - modèles `NoyauStable`, `CoucheNarrative`, `Arc`, modèle racine `AnalyseChapter`,
   - `min_length=1` sur les champs textuels obligatoires, `max_length` sur les listes plafonnées (`pistes_traduction` ≤ 15).
2. Réécrire `phase/analyze_chapter_layered_system.jinja` :
   - retirer la "Structure JSON attendue",
   - retirer "Format de sortie",
   - **conserver** intégralement la logique de modes (`bootstrap` / `seed` / `incremental`) et les consignes spécifiques à chacun,
   - **conserver** les budgets non exprimables en schéma (lignes, phrases),
   - **conserver** les règles d'annotation des arcs (sémantique de `signal_cloture`).
3. Côté orchestrateur : appel Instructor `Mode.TOOLS_STRICT` avec `response_model=AnalyseChapter`. Sérialisation du snapshot précédent par `existing_analysis = previous_snapshot.model_dump_json()` à injecter dans le `_user.jinja`.
4. Vérifier la chaîne complète sur un chapitre multi-blocs : bootstrap → incrémental → dernier bloc. Vérifier la transmission de la fiche finale en `previous_chapter_analysis` du chapitre suivant.
5. Mesurer la stabilité du `noyau_stable` entre blocs (régression possible : le strict mode pourrait inciter le LLM à reformuler systématiquement, à surveiller).

## Pièges et points d'attention

- **Latence du strict mode** : compilation de la grammaire à la première requête sur un schéma donné. À mesurer côté DeepSeek V4 ; potentiellement amorti par le cache au-delà du premier appel.
- **Coût des retries** : chaque retry réinjecte l'historique enrichi de la `ValidationError`. Sur des schémas profonds, le contexte gonfle vite. Plafonner `max_retries`.
- **Messages de validators** : ce sont les **vrais prompts de correction**. Ils sont destinés au LLM, pas aux développeurs. Les rédiger en suivant les principes du `CLAUDE.md` (déclaratif, neutre, citer la valeur reçue et les valeurs attendues).
- **Évolution du schéma** : un changement du `BaseModel` modifie le schéma envoyé au LLM, ce qui peut invalider les caches DeepSeek de grammaire. Prévoir un test de non-régression sur un échantillon de référence après chaque modification.
- **Sérialisation des snapshots** (`analyze_chapter_layered`) : `model_dump_json()` produit un JSON différent du JSON brut renvoyé par le LLM (ordre des champs, échappements). Pour la trace et les comparaisons, fixer l'ordre via `model_config` ou documenter la différence.
- **Disparition des `retry_correct_analysis_*`** (hors périmètre, mais factuel) : Instructor + strict mode rend ces deux templates structurellement obsolètes. Les supprimer une fois la migration validée.
- **Compatibilité de `extra="forbid"` avec l'évolution** : ajouter un champ au schéma casse la rétrocompatibilité avec les snapshots produits par une version antérieure. À gérer côté orchestrateur (versioning des snapshots) si la reprise inter-livre est attendue.
- **Pas d'arbitrage métier dans les validators** : tentation à éviter. La priorité d'arbitrage du glossaire (`personnage > creature > …`) reste dans l'orchestrateur. Pydantic vérifie que `type` est une valeur valide, pas que c'est la "bonne" valeur étant donné les autres champs.

## Hors périmètre du guide

- Templates de retry pour la **traduction** (`retry_translate_*`, `retry_correct_fragments_*`, `retry_correct_punctuation_*`).
- Templates de retry JSON existants (`retry_correct_analysis_invalid_json_*`, `retry_correct_analysis_missing_sections_*`) : à supprimer en pratique, mais traités hors guide.
- Phase d'analyse non-stratifiée `analyze_chapter` : dépréciée, ne pas migrer.
- Pipeline d'agrégation et d'arbitrage du glossaire côté orchestrateur (logique métier, indépendante du schéma).
- Phases de traduction `translate_base` / `translate_refine` : pas de sortie JSON, non concernées.

## Références

- Documentation Pydantic : https://docs.pydantic.dev/
- Documentation Instructor : https://python.useinstructor.com/
- Concepts de prompting Instructor : https://python.useinstructor.com/concepts/prompting/ — recommandations sur l'usage des `Field(description=...)`, des docstrings, des validators avec messages explicites, et des patterns "chain-of-thought via field ordering" (placer un champ `reasoning: str` avant le champ de réponse finale pour induire une réflexion). À recouper avec la doc à jour.
- DeepSeek V4 — JSON mode : https://api-docs.deepseek.com/guides/json_mode
- DeepSeek V4 — Tool calls : https://api-docs.deepseek.com/guides/tool_calls
- Conventions de rédaction internes : `CLAUDE.md` à la racine du repo (section "Principes de rédaction des prompts").
