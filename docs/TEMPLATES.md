# Architecture des templates LLM

Les templates Jinja2 vivent dans le paquet [src/template/](../src/template/). Ils sont rendus via `TemplateRenderer` ([llm/template_renderers.py](../src/ebook_translator/llm/template_renderers.py)), dont le `prompt_dir` pointe la racine de ce paquet.

## Convention : une paire par prompt

Chaque prompt est constitué de **deux fichiers** — le message système et le message utilisateur :

```
<nom>_system.jinja   →  system_prompt
<nom>_user.jinja     →  user_instruction
```

Les deux sont résolus ensemble par l'enum `Template` et ses deux sous-enums, qui portent chacune son préfixe de répertoire :

| Enum | Préfixe | Rôle |
|---|---|---|
| `PhaseTemplate` | `phase/` | Prompt principal d'une phase |
| `RetryTemplate` | `retry/` | Prompt de correction après échec de validation |

`Template.get_templates()` retourne le couple `(system, user)` ; `render_prompt(template, **params)` rend les deux et retourne un tuple.

## Arborescence

```
template/
├── common/     # fragments partagés, inclus par {% include %}
├── phase/      # prompts de phase
└── retry/      # prompts de correction
```

### Fragments communs (`common/`)

| Fichier | Contenu |
|---|---|
| `common_translate_rules.jinja` | Règles générales de traduction (fidélité, style, balises `<N/>` et `</>`, exemples, format de sortie) |
| `common_translate_rules_light.jinja` | Version allégée, utilisée par les retries de traduction |
| `common_correct_rules.jinja` | Règles de correction (minimalisme, préservation du sens, comptage exact des balises) |
| `glossary_block.jinja` | Injection du glossaire dans les prompts de traduction |
| `glossary_existing_block.jinja` | Termes déjà connus, pour la phase glossaire |
| `literary_context_block.jinja` | Contexte littéraire issu de Phase 0 |

### Templates de phase (`phase/`)

| Membre de `PhaseTemplate` | Fichiers | Phase |
|---|---|---|
| `First_Pass_Template` | `translate_base_*` | Phase 1 — traduction initiale |
| `Refine_Template` | `translate_refine_*` | Phase 2 — raffinage (glossaire + traduction précédente) |
| `Analyze_Chapter` | `analyze_chapter_*` | Phase 0 — analyse simple |
| `Analyze_Chapter_Layered` | `analyze_chapter_layered_*` | Phase 0 — analyse stratifiée (`AnalyseChapter`) |
| `Glossary` | `glossary_*` | Phase glossaire |

### Templates de correction (`retry/`)

| Membre de `RetryTemplate` | Fichiers | Déclenché par |
|---|---|---|
| `Retry_Missing_Lines_Targeted_Template` | `retry_translate_missing_lines_targeted_*` | `LineCountCheck` |
| `Retry_Sentence_Template` | `retry_translate_sentence_*` | `SentenceCheck` |
| `Retry_Fragments_Template` | `retry_correct_fragments_*` | `FragmentCountCheck` |
| `Retry_Punctuation_Template` | `retry_correct_punctuation_*` | `PunctuationCheck` |
| `Retry_Analysis_Invalid_Json_Template` | `retry_correct_analysis_invalid_json_*` | Analyse — JSON invalide |
| `Retry_Analysis_Missing_Sections_Template` | `retry_correct_analysis_missing_sections_*` | Analyse — sections manquantes |

L'association `error_type` → template est portée par `RETRY_REGISTRY` ([llm/retry_registry.py](../src/ebook_translator/llm/retry_registry.py)), pas par les checks. Voir [VALIDATION.md](VALIDATION.md).

## Variables de template

Les paramètres de chaque template sont des `TypedDict` déclarés dans [template/template_params.py](../src/template/template_params.py) — c'est la source de vérité :

`AnalyzeChapterParams`, `AnalyzeChapterLayeredParams`, `GlossaryParams`, `TranslateParams`, `RefineParams`, `MissingLinesParams`, `RetryFragmentsParams`, `RetryPunctuationParams`, `RetrySentenceParams`, `RetryAnalysisInvalidJsonParams`, `RetryAnalysisMissingSectionsParams`.

Pour les prompts de correction, chaque `RetryEntry` du registre déclare son `params_type` et la fonction `build` qui le remplit depuis le diagnostic typé.

Côté renderer, une méthode typée par prompt : `render_translate()`, `render_refine()`, `render_analyze_chapter()`, `render_analyze_chapter_layered()`, `render_glossary()`, `render_missing_lines()`, `render_retry_fragments()`, `render_retry_punctuation()`, `render_retry_sentence()`, `render_retry_analysis_invalid_json()`, `render_retry_analysis_missing_sections()`.

Deux variables sont portées par le renderer lui-même et injectées dans tous les rendus : le **genre littéraire** (`set_genre()`, défaut `"fiction"`) et le **plafond de termes de glossaire** (`glossary_max_terms`, défaut 25).

L'extraction des variables déclarées par un fichier Jinja2 est outillée par [llm/template_params.py](../src/ebook_translator/llm/template_params.py).

## Format de sortie LLM attendu

Les templates de traduction demandent systématiquement :

- chaque ligne préfixée par `<N/>`, même numérotation que l'entrée
- séparateurs `</>` préservés en nombre et position exacts
- terminaison par `[=[END]=]`

Ce format n'a qu'une **source de vérité** : le modèle `LineIndexedLLMResponse` ([template/phase/translation_models.py](../src/template/phase/translation_models.py)), qui le valide au parse.

### Sortie de la phase glossaire

La phase glossaire a son propre format textuel, tabulaire : une ligne par terme, quatre colonnes séparées par `|`, terminée par le même `[=[END]=]`.

```
Alice|personnage|f|Alice
White Rabbit|creature|m|Lapin Blanc
[=[END]=]
```

Source de vérité : `LLMGlossaryModel` ([template/phase/glossary_models.py](../src/template/phase/glossary_models.py)), qui parse la chaîne brute dans un validateur `mode="before"`. À structure égale, l'enveloppe JSON qu'il remplace coûtait deux fois plus de tokens **de sortie** par entrée (22,4 contre 12,4), et faisait injecter en entrée le schéma JSON du modèle à chaque appel.

Une ligne dont la cardinalité n'est pas 4, ou dont `type`/`sexe` sort des valeurs autorisées, est **écartée avec un `WARNING`** plutôt que corrigée par un appel supplémentaire : le glossaire est un agrégat pondéré sur tout l'ouvrage, où perdre un terme est sans conséquence. Les puces et numérotations en tête de ligne sont nettoyées. Seules la génération tronquée (`[=[END]=]` absent) et la réponse dont aucune ligne n'est exploitable font échouer le chunk.

Phase 0 reste la seule phase à sortie structurée : elle passe par Instructor sur son schéma Pydantic `AnalyseChapter`.
