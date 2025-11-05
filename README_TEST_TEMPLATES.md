# 🧪 Test Manuel des Templates

Ce guide explique comment tester manuellement les templates refactorisés.

## 📋 Scripts Disponibles

### `test_template_manual.py`
Script principal pour tester un template à la fois avec rendu complet du prompt.

### Usage

```bash
# Lister tous les templates disponibles
poetry run python test_template_manual.py list

# Tester un template spécifique
poetry run python test_template_manual.py <template_name>
```

## 🎯 Templates Disponibles

### TRANSLATE Templates (Créer des traductions)

| Nom du template | Fichier | Description |
|-----------------|---------|-------------|
| `translate_base` | `translate_base.jinja` | Phase 1 - Traduction initiale (chunks 2000 tokens) |
| `translate_refine` | `translate_refine.jinja` | Phase 2 - Raffinage avec glossaire (chunks 300 tokens) |
| `retry_translate_missing` | `retry_translate_missing_lines_targeted.jinja` | Retraduire lignes manquantes |
| `retry_translate_sentence` | `retry_translate_sentence.jinja` | Retraduire contenu tronqué |

### CORRECT Templates (Corriger erreurs structurelles)

| Nom du template | Fichier | Description |
|-----------------|---------|-------------|
| `retry_correct_fragments` | `retry_correct_fragments.jinja` | Corriger nombre séparateurs `</>` (STRICT) |
| `retry_correct_fragments_flexible` | `retry_correct_fragments_flexible.jinja` | Corriger nombre séparateurs `</>` (FLEXIBLE) |
| `retry_correct_punctuation` | `retry_correct_punctuation.jinja` | Corriger paires de guillemets |

## 📖 Exemples d'Utilisation

### Tester Phase 1 (traduction initiale)

```bash
poetry run python test_template_manual.py translate_base
```

**Sortie** :
```
================================================================================
📝 Template: translate_base
📄 Fichier: translate_base.jinja
================================================================================

🔧 Paramètres utilisés:
  - target_language: français

📊 Statistiques:
  - Longueur: 6182 caractères
  - Lignes: 212
  - Inclut règles communes: ✅ Oui

================================================================================
📄 RENDU DU PROMPT:
================================================================================

[... prompt complet affiché ...]
```

### Tester Phase 2 (raffinage)

```bash
poetry run python test_template_manual.py translate_refine
```

### Tester une correction de ponctuation

```bash
poetry run python test_template_manual.py retry_correct_punctuation
```

## 🔧 Modifier les Paramètres de Test

Pour tester avec des paramètres personnalisés, éditez le dictionnaire `TEMPLATES` dans `test_template_manual.py` :

```python
TEMPLATES = {
    "translate_base": {
        "file": "translate_base.jinja",
        "params": {
            "target_language": "español"  # Changer la langue cible
        }
    },
    # ...
}
```

## ✅ Vérifications Automatiques

Le script vérifie automatiquement :

- ✅ Le template se rend sans erreur
- ✅ Longueur et nombre de lignes du prompt
- ✅ Présence des règles communes (via `{% include %}`)
- ✅ Structure complète du prompt

## 🎨 Sortie Attendue

Chaque test affiche :

1. **Métadonnées** : Nom du template et fichier
2. **Paramètres** : Valeurs utilisées pour le rendu
3. **Statistiques** : Longueur, lignes, inclusions
4. **Prompt complet** : Rendu final du template

## 🚀 Workflow de Test Recommandé

```bash
# 1. Lister les templates
poetry run python test_template_manual.py list

# 2. Tester chaque catégorie

# TRANSLATE
poetry run python test_template_manual.py translate_base
poetry run python test_template_manual.py translate_refine
poetry run python test_template_manual.py retry_translate_missing
poetry run python test_template_manual.py retry_translate_sentence

# CORRECT
poetry run python test_template_manual.py retry_correct_fragments
poetry run python test_template_manual.py retry_correct_fragments_flexible
poetry run python test_template_manual.py retry_correct_punctuation
```

## 📊 Validation de la Refactorisation

Pour valider que la refactorisation n'a pas cassé les templates :

```bash
# Pour chaque template, vérifier :
# 1. Le prompt se rend sans erreur ✅
# 2. Les règles communes sont incluses ✅
# 3. Le prompt contient toutes les sections attendues ✅
```

### Sections à Vérifier (TRANSLATE)

- ✅ `Règles de traduction`
- ✅ `Traduire TOUTES les lignes`
- ✅ `Gestion des balises`
- ✅ `Contexte`
- ✅ `Format de sortie`
- ✅ `[=[END]=]`
- ✅ Exemples de traduction

### Sections à Vérifier (CORRECT)

- ✅ `ANALYSE DE L'ERREUR`
- ✅ `Philosophie de correction`
- ✅ `Gestion des balises`
- ✅ `Format de sortie`
- ✅ `Checklist`
- ✅ Exemples de correction

## 🐛 Dépannage

### Erreur: `ModuleNotFoundError: No module named 'jinja2'`

```bash
# Solution: Utiliser poetry run
poetry run python test_template_manual.py list
```

### Erreur: `UnicodeEncodeError` (Windows)

Le script contient déjà un fix pour Windows. Si l'erreur persiste :

```bash
# Définir l'encodage UTF-8
set PYTHONIOENCODING=utf-8
poetry run python test_template_manual.py list
```

## 📝 Notes

- Les templates utilisent `{% include %}` pour inclure les règles communes
- Les règles communes sont dans `template/common_translate_rules.jinja` et `template/common_correct_rules.jinja`
- Le rendu final contient TOUT le contenu (base + spécifique)
- Les paramètres par défaut sont minimaux mais suffisants pour tester le rendu
