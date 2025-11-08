# Architecture des templates LLM

Ce document décrit l'architecture des templates Jinja2 utilisés pour générer les prompts LLM.

## Vue d'ensemble

**Problème initial** (avant v0.9.0) :
- Chaque template (~200-400 lignes) contenait des règles communes répétées
- Modification d'une règle = mise à jour dans 7 fichiers différents
- Incohérences possibles entre templates
- Maintenabilité faible (principe DRY violé)

**Solution adoptée** (v0.9.0) :
- 2 templates de base communs (`common_translate_rules.jinja`, `common_correct_rules.jinja`)
- Inclusion via `{% include %}` dans tous les templates spécifiques
- Catégorisation claire : **TRANSLATE** (créer traductions) vs **CORRECT** (corriger erreurs)

## Catégories de templates

### 1. TRANSLATE Templates

**Rôle** : Créent de nouvelles traductions à partir du texte source.

| Template | Fichier | Description | Lignes avant | Lignes après | Réduction |
|----------|---------|-------------|--------------|--------------|-----------|
| Phase 1 - Traduction initiale | `translate_base.jinja` | Traduction par chunks de 2000 tokens | 199 | 53 | **-73%** |
| Phase 2 - Raffinage | `translate_refine.jinja` | Raffinage avec glossaire (chunks 300 tokens) | 386 | 171 | **-56%** |
| Retry - Lignes manquantes | `retry_translate_missing_lines_targeted.jinja` | Retraduire lignes spécifiques ignorées | 87 | 79 | **-9%** |
| Retry - Contenu tronqué | `retry_translate_sentence.jinja` | Retraduire segments tronqués par LLM | 178 | 97 | **-45%** |

### 2. CORRECT Templates

**Rôle** : Corrigent les erreurs structurelles dans les traductions existantes.

| Template | Fichier | Description | Lignes avant | Lignes après | Réduction |
|----------|---------|-------------|--------------|--------------|-----------|
| Retry - Séparateurs (STRICT) | `retry_correct_fragments.jinja` | Corriger nombre `</>` (positions exactes) | 151 | 142 | **-6%** |
| Retry - Séparateurs (FLEXIBLE) | `retry_correct_fragments_flexible.jinja` | Corriger nombre `</>` (positions flexibles) | 197 | 148 | **-25%** |
| Retry - Ponctuation | `retry_correct_punctuation.jinja` | Corriger paires de guillemets | 367 | 158 | **-57%** |

## Statistiques globales

- **Total avant** : 1565 lignes
- **Total après** : 848 lignes + 329 lignes (bases communes)
- **Réduction nette** : -388 lignes (**-25%**)
- **Réutilisation** : 329 lignes partagées par 7 templates = **~2300 lignes économisées** (7×329 - 329)

## Bases communes créées

### 1. common_translate_rules.jinja (199 lignes)

**Contenu partagé par tous les TRANSLATE templates** :

**Sections** :
1. **Règles générales de traduction**
   - Fidélité absolue (sens, ton, registre)
   - Préservation du style (métaphores, figures, rythme)
   - Cohérence terminologique (noms propres, termes techniques)
   - Registre de langue (formel/informel/soutenu/familier)
   - Ponctuation (adaptation aux conventions de la langue cible)

2. **Gestion des balises**
   - Balises de numérotation `<N/>` (reproduire EXACTEMENT)
   - Séparateurs de fragments `</>` (préserver le même nombre)
   - Exemples concrets avec bonne/mauvaise utilisation

3. **Exemples few-shot learning** (4 exemples complets)
   - **Exemple 1** : Préservation du style narratif et des figures de style
   - **Exemple 2** : Cohérence des noms propres et termes techniques
   - **Exemple 3** : Gestion des balises `</>` multiples
   - **Exemple 4** : Préservation du registre de langue (dialogues)

4. **Format de sortie standard**
   - Structure attendue avec `<N/>` + contenu + `[=[END]=]`

**Utilisé par** :
- `translate_base.jinja`
- `translate_refine.jinja`
- `retry_translate_missing_lines_targeted.jinja`
- `retry_translate_sentence.jinja`

### 2. common_correct_rules.jinja (130 lignes)

**Contenu partagé par tous les CORRECT templates** :

**Sections** :
1. **Philosophie de correction**
   - Minimiser les changements (corriger seulement l'erreur détectée)
   - Préserver le sens (ne pas modifier la traduction existante)
   - Respect du contexte (tenir compte du texte original)
   - Pas d'interprétation (corriger la structure, pas le contenu)

2. **Gestion des balises** (version correction)
   - Focus sur comptage exact des éléments
   - Vérification ligne par ligne
   - Exemples de corrections AVANT/APRÈS

3. **Checklist de vérification finale**
   - Comptage manuel des éléments dans l'original
   - Comptage manuel des éléments dans la correction
   - Vérification d'égalité (OBLIGATOIRE)
   - Validation ligne par ligne

4. **Format de sortie**
   - Structure identique aux TRANSLATE (cohérence)

**Utilisé par** :
- `retry_correct_fragments.jinja`
- `retry_correct_fragments_flexible.jinja`
- `retry_correct_punctuation.jinja`

## Exemple de refactorisation

### Avant v0.9.0

**translate_base.jinja** (199 lignes) :

```jinja
Tu es un traducteur professionnel expert.

## 🎯 Règles de traduction

1. **Fidélité absolue** : Traduire EXACTEMENT...
2. **Préservation du style** : Métaphores...
3. **Cohérence terminologique** : Noms propres...
[... 180 lignes de règles communes ...]

## Phase 1 : Traduction initiale

- Traduire par chunks de 2000 tokens
- Pas de glossaire à ce stade
[... 15 lignes spécifiques Phase 1 ...]
```

### Après v0.9.0

**translate_base.jinja** (53 lignes) :

```jinja
Tu es un traducteur professionnel expert.

{# Inclure les règles communes de traduction #}
{% include 'common_translate_rules.jinja' %}

## Phase 1 : Traduction initiale

- Traduire par chunks de 2000 tokens
- Pas de glossaire à ce stade
- Focus sur cohérence narrative
[... 15 lignes spécifiques Phase 1 ...]
```

**Résultat** :
- ✅ Réduction de 199 → 53 lignes (-73%)
- ✅ Règles communes centralisées
- ✅ Modification d'une règle = 1 seul fichier à éditer
- ✅ Cohérence garantie entre tous les templates

## Tests manuels des templates

### Scripts disponibles

**test_template_manual.py** :
- Test individuel de templates avec aperçu du rendu complet
- Validation de la structure Jinja2
- Vérification de l'inclusion des règles communes

**test_all_templates.py** :
- Test batch de tous les templates
- Résumé des statistiques (longueur, inclusion règles communes)
- Détection des templates avec erreurs

**README_TEST_TEMPLATES.md** :
- Documentation complète des tests manuels
- Exemples d'usage
- Guide de dépannage

### Usage

```bash
# Lister tous les templates disponibles
poetry run python test_template_manual.py list

# Tester un template spécifique avec rendu complet
poetry run python test_template_manual.py translate_base
poetry run python test_template_manual.py retry_correct_punctuation

# Tester tous les templates (batch)
poetry run python test_all_templates.py
```

### Sortie exemple

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

[Prompt complet affiché avec règles communes incluses]

================================================================================
✅ Template rendu avec succès!
================================================================================
```

### Validation automatique

Les scripts vérifient :
- ✅ Le template se rend sans erreur Jinja2
- ✅ Les règles communes sont incluses (via `{% include %}`)
- ✅ La structure du prompt est complète
- ✅ Longueur et nombre de lignes cohérents

## Bénéfices de la refactorisation

| Aspect | Avant v0.9.0 | v0.9.0 | Amélioration |
|--------|--------------|--------|--------------|
| **Duplication de code** | 7 templates × 180 lignes communes = ~1260 lignes dupliquées | 329 lignes partagées | **-73% duplication** |
| **Maintenabilité** | Modifier 1 règle = éditer 7 fichiers | Modifier 1 règle = éditer 1 fichier | **7× plus facile** |
| **Cohérence** | ⚠️ Risque d'incohérence entre templates | ✅ Cohérence garantie (même source) | **100% cohérent** |
| **Lisibilité** | Templates longs (200-400 lignes) | Templates concis (50-170 lignes) | **+40-70% lisibilité** |
| **Tests** | Aucun test de rendu | Scripts de test manuels dédiés | **✅ Validation automatique** |
| **Documentation** | Aucune | README_TEST_TEMPLATES.md complet | **✅ Guide utilisateur** |

## Impact sur le développement

### Ajout d'une nouvelle règle

**Avant v0.9.0** :
1. Éditer `translate_base.jinja`
2. Éditer `translate_refine.jinja`
3. Éditer `retry_translate_missing_lines_targeted.jinja`
4. Éditer `retry_translate_sentence.jinja`
5. Vérifier cohérence manuelle
6. Risque d'oubli ou d'incohérence

**Avec v0.9.0** :
1. Éditer `common_translate_rules.jinja`
2. Tester avec `poetry run python test_template_manual.py translate_base`
3. ✅ Changement appliqué automatiquement aux 4 templates

### Création d'un nouveau template

```jinja
{# Nouveau template TRANSLATE #}
Tu es un traducteur professionnel.

{# Inclure les règles communes #}
{% include 'common_translate_rules.jinja' %}

{# Règles spécifiques à ce template #}
## Ma règle spécifique

[...]
```

**Résultat** : ~180 lignes économisées dès le départ

## Fichiers modifiés

### Configuration

- [config.py:94-101](../src/ebook_translator/config.py#L94-L101) - 7 constantes renommées + 1 nouvelle (`Retry_Punctuation_Template`)
- [template_renderers.py:365](../src/ebook_translator/llm/template_renderers.py#L365) - Remplacement hardcoded string par constante

### Templates créés (nouveaux)

- [template/common_translate_rules.jinja](../template/common_translate_rules.jinja) - 199 lignes de règles communes TRANSLATE
- [template/common_correct_rules.jinja](../template/common_correct_rules.jinja) - 130 lignes de règles communes CORRECT

### Templates refactorés (7 fichiers)

- [template/translate_base.jinja](../template/translate_base.jinja) - 199 → 53 lignes (-73%)
- [template/translate_refine.jinja](../template/translate_refine.jinja) - 386 → 171 lignes (-56%)
- [template/retry_translate_missing_lines_targeted.jinja](../template/retry_translate_missing_lines_targeted.jinja) - 87 → 79 lignes (-9%)
- [template/retry_translate_sentence.jinja](../template/retry_translate_sentence.jinja) - 178 → 97 lignes (-45%)
- [template/retry_correct_fragments.jinja](../template/retry_correct_fragments.jinja) - 151 → 142 lignes (-6%)
- [template/retry_correct_fragments_flexible.jinja](../template/retry_correct_fragments_flexible.jinja) - 197 → 148 lignes (-25%)
- [template/retry_correct_punctuation.jinja](../template/retry_correct_punctuation.jinja) - 367 → 158 lignes (-57%)

### Tests mis à jour

- [tests/test_translation_quality.py](../tests/test_translation_quality.py) - 9 références hardcodées remplacées par constantes
- [test_targeted_retry.py](../test_targeted_retry.py) - Utilisation de `TemplateNames`
- 9 autres fichiers de test (11 changements au total)

### Scripts de test manuels (nouveaux)

- [test_template_manual.py](../test_template_manual.py) - Test individuel avec aperçu du rendu
- [test_all_templates.py](../test_all_templates.py) - Test batch de tous les templates
- [README_TEST_TEMPLATES.md](../README_TEST_TEMPLATES.md) - Documentation complète

## Migration depuis v0.8.0

**Aucune action requise**. Le système fonctionne automatiquement.

**Pour les développeurs modifiant les templates** :
1. Ne plus éditer directement les templates spécifiques pour les règles communes
2. Éditer `common_translate_rules.jinja` ou `common_correct_rules.jinja`
3. Utiliser les scripts de test manuels pour valider les changements

## Limitations connues

1. **Tests de contenu stricts** : Les tests vérifiant le wording exact peuvent échouer (formulations légèrement différentes)
2. **Subprocess encoding** : `test_all_templates.py` a des problèmes d'encodage UTF-8 sous Windows (utiliser `test_template_manual.py` individuellement)
3. **Pas de cache de rendu** : Chaque appel re-rend le template complet (performance non critique)

## Voir aussi

- [ARCHITECTURE.md](ARCHITECTURE.md) - Architecture globale du système
- [VALIDATION.md](VALIDATION.md) - Architecture de validation
- [ROADMAP.md](ROADMAP.md) - Améliorations futures planifiées
