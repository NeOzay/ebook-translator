# Architecture des templates LLM

Les templates Jinja2 sont dans `template/`. Ils sont rendus via `TemplateRenderer` ([llm/template_renderers.py](../src/ebook_translator/llm/template_renderers.py)).

## Structure DRY

Deux bases communes partagées par inclusion `{% include %}` :

- **`common_translate_rules.jinja`** : règles générales de traduction (fidélité, style, balises `<N/>` et `</>`, exemples few-shot, format de sortie)
- **`common_correct_rules.jinja`** : règles de correction (minimalisme, préservation du sens, comptage exact des balises, checklist)

## Templates de traduction (TRANSLATE)

| Template | Phase | Description |
|----------|-------|-------------|
| `translate_base.jinja` | Phase 1 | Traduction initiale — pas de glossaire |
| `translate_refine.jinja` | Phase 2 | Raffinage avec glossaire + traduction précédente |
| `retry_translate_missing_lines_targeted.jinja` | Retry | Retraduire des lignes spécifiques manquantes |
| `retry_translate_sentence.jinja` | Retry | Retraduire des segments tronqués |

## Templates de correction (CORRECT)

| Template | Check associé | Description |
|----------|--------------|-------------|
| `retry_correct_fragments.jinja` | `FragmentCountCheck` | Corriger le nombre de `</>` (positions exactes) |
| `retry_correct_fragments_flexible.jinja` | `FragmentCountCheck` | Corriger le nombre de `</>` (positions flexibles) |
| `retry_correct_punctuation.jinja` | `PunctuationCheck` | Rééquilibrer les paires de guillemets |

## Template d'analyse (Phase 0)

| Template | Description |
|----------|-------------|
| `analyze_chapter_simplified.jinja` | Analyse littéraire en JSON mode — génère un `ContexteTraduction` |

## Format de sortie LLM attendu

Les templates de traduction demandent systématiquement :
- Chaque ligne préfixée par `<N/>` (même numérotation que l'entrée)
- Séparateurs `</>` préservés en nombre et position exacts
- Terminaison par `[=[END]=]`

Ce format est parsé par [translation/parser.py](../src/ebook_translator/translation/parser.py).

## Variables de template

Les variables disponibles dans chaque template sont définies dans les méthodes typées de `TemplateRenderer`. Pour connaître les variables d'un template, voir :
- La méthode `render_*()` correspondante dans [llm/template_renderers.py](../src/ebook_translator/llm/template_renderers.py)
- Le fichier [llm/template_params.py](../src/ebook_translator/llm/template_params.py) pour l'extraction des variables Jinja2
