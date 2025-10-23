# Guide de validation du glossaire

## Vue d'ensemble

Le système de validation du glossaire garantit la cohérence terminologique entre la Phase 1 (traduction initiale) et la Phase 2 (affinage). Il permet de détecter et résoudre les conflits avant que le glossaire ne soit utilisé pour affiner les traductions.

## Fonctionnement

### 1. Déclenchement automatique

La validation est déclenchée automatiquement dans le `TwoPhasePipeline` entre Phase 1 et Phase 2 :

```python
pipeline = TwoPhasePipeline(llm, "book.epub", Path("cache"))
stats = pipeline.run(
    target_language="fr",
    output_epub="book_fr.epub",
    auto_validate_glossary=False,  # Mode interactif (défaut)
)
```

### 2. Vérifications préalables

Avant la validation du glossaire, le système vérifie :

1. **Queue d'erreurs vide** : Toutes les erreurs de Phase 1 doivent être corrigées
   - Timeout de 60 secondes avec polling toutes les 2 secondes
   - Si timeout expiré → `RuntimeError` (transition bloquée)

2. **Statistiques du glossaire** : Affichage du nombre de termes appris, validés, en conflit

### 3. Détection des conflits

Un conflit est détecté quand :
- Un terme source a au moins 2 traductions différentes
- Aucune traduction ne domine à >70%

**Exemple de conflit** :
```
Matrix:
  - 'Matrice' (12×, 48%)
  - 'Système' (13×, 52%)
```

### 4. Résolution interactive

Pour chaque conflit, l'utilisateur peut :

| Commande | Action | Exemple |
|----------|--------|---------|
| `1`, `2`, `3`... | Choisir une traduction spécifique | `1` → Choisir 'Matrice' |
| `a` | Résolution automatique (choix le plus fréquent) | Choisit 'Système' (52%) |
| `s` | Passer (sera résolu auto à la fin) | Résolu avec le plus fréquent |
| `q` | Quitter sans valider | Bloque la transition vers Phase 2 |

**Workflow interactif** :
```
[1/3] Terme: 'Matrix'
  1. 'Matrice' (12×, 48%)
  2. 'Système' (13×, 52%)
Votre choix: 1
✅ Validé: Matrix → Matrice
```

### 5. Validation finale

Après résolution de tous les conflits :
- Demande de confirmation à l'utilisateur
- Sauvegarde du glossaire validé sur disque
- Passage à la Phase 2

## Modes d'utilisation

### Mode interactif (défaut)

L'utilisateur est invité à résoudre chaque conflit manuellement :

```python
stats = pipeline.run(
    target_language="fr",
    output_epub="book_fr.epub",
    auto_validate_glossary=False,  # Mode interactif
)
```

**Avantages** :
- ✅ Contrôle total sur les choix de traduction
- ✅ Permet de prendre en compte le contexte et le style
- ✅ Garantit la cohérence selon les préférences de l'utilisateur

**Inconvénients** :
- ⚠️ Requiert interaction humaine (non adapté aux workflows automatisés)
- ⚠️ Peut être long si beaucoup de conflits

### Mode automatique

Les conflits sont résolus automatiquement (traduction la plus fréquente) :

```python
stats = pipeline.run(
    target_language="fr",
    output_epub="book_fr.epub",
    auto_validate_glossary=True,  # Mode automatique
)
```

**Avantages** :
- ✅ Adapté aux workflows CI/CD
- ✅ Rapide (pas d'attente utilisateur)
- ✅ Déterministe (basé sur fréquence)

**Inconvénients** :
- ⚠️ Pas de contrôle humain
- ⚠️ Peut choisir une traduction sous-optimale

**Quand utiliser** :
- Tests automatisés
- Pipelines CI/CD
- Traductions en batch
- Prototypes rapides

## Utilisation standalone

Le `GlossaryValidator` peut être utilisé indépendamment du pipeline :

```python
from ebook_translator.glossary import Glossary
from ebook_translator.pipeline.glossary_validator import GlossaryValidator
from pathlib import Path

# Charger un glossaire existant
glossary = Glossary(cache_path=Path("cache/glossary.json"))

# Valider
validator = GlossaryValidator(glossary)
is_valid = validator.validate_interactive(auto_resolve=False)

if is_valid:
    print("✅ Glossaire validé")
    glossary.save()  # Sauvegarder avec les validations
else:
    print("❌ Validation annulée")
```

## Export du résumé

Générer un rapport textuel du glossaire validé :

```python
validator = GlossaryValidator(glossary)
summary = validator.export_summary()
print(summary)
```

**Format du résumé** :
```
============================================================
📚 RÉSUMÉ DU GLOSSAIRE VALIDÉ
============================================================

📊 Statistiques:
  • Termes appris: 42
  • Termes validés: 38
  • Conflits résolus: 4

📖 Termes haute confiance (échantillon):
  • Matrix → Matrice
  • DNA → ADN
  • Protocol → Protocole
  ... et 35 autre(s) terme(s)
============================================================
```

## Gestion des erreurs

### Erreur : Timeout corrections

```
❌ Impossible de passer à la Phase 2: 3 erreur(s) non corrigée(s)
  • Corrigées: 42
  • Échouées: 1
  • En attente: 3
Veuillez vérifier les logs pour plus de détails.
```

**Solutions** :
1. Vérifier les logs de correction
2. Analyser les chunks échoués
3. Corriger manuellement ou augmenter `correction_timeout`

### Erreur : Validation annulée

```
❌ Validation du glossaire annulée par l'utilisateur.
La Phase 2 ne peut pas démarrer sans un glossaire validé.
```

**Solutions** :
1. Relancer avec `auto_validate_glossary=True`
2. Relancer et valider le glossaire manuellement
3. Corriger le glossaire manuellement puis relancer

## Bonnes pratiques

### 1. Préparation du glossaire

- ✅ Ajouter des termes spécifiques au domaine avant Phase 1
- ✅ Utiliser `glossary.validate_translation()` pour pré-valider des termes clés
- ✅ Charger un glossaire existant depuis un projet similaire

```python
# Pré-validation de termes clés
glossary = Glossary(cache_path=Path("cache/glossary.json"))
glossary.validate_translation("Matrix", "Matrice")
glossary.validate_translation("Protocol", "Protocole")
glossary.save()
```

### 2. Résolution des conflits

- ✅ Privilégier la traduction la plus cohérente avec le style du livre
- ✅ Vérifier le contexte d'utilisation dans l'EPUB source
- ✅ Utiliser `s` (skip) pour les conflits complexes, réviser à la fin
- ⚠️ Éviter `q` (quit) sauf si vraiment nécessaire

### 3. Workflows recommandés

**Première traduction** :
```python
# Mode interactif pour validation humaine
pipeline.run(..., auto_validate_glossary=False)
```

**Re-traduction avec glossaire existant** :
```python
# Charger glossaire validé précédemment
glossary = Glossary(cache_path=Path("cache/glossary.json"))
# Mode automatique possible
pipeline.run(..., auto_validate_glossary=True)
```

**Tests et CI/CD** :
```python
# Toujours automatique
pipeline.run(..., auto_validate_glossary=True)
```

## Exemples complets

Voir [example_pipeline.py](../example_pipeline.py) pour des exemples détaillés :
- Validation interactive standard
- Validation automatique pour CI/CD
- Nettoyage des caches

## Dépannage

### Aucun conflit détecté mais traductions incohérentes

**Cause** : Le seuil de dominance (70%) masque certains conflits

**Solution** : Ajuster manuellement le glossaire
```python
# Vérifier les termes avec confiance moyenne
mid_conf = glossary.get_high_confidence_terms(min_confidence=0.5)
for term, translation in mid_conf.items():
    print(f"{term} → {translation}")
```

### Trop de conflits à résoudre

**Cause** : Phase 1 avec trop de variabilité (température élevée, chunks trop petits)

**Solutions** :
1. Réduire la température LLM (< 0.5)
2. Augmenter `phase1_max_tokens` (plus de contexte)
3. Utiliser `auto_validate_glossary=True` en première passe

### Validation bloquée par erreurs persistantes

**Cause** : Certains chunks échouent systématiquement en Phase 1

**Solutions** :
1. Analyser les logs de correction
2. Vérifier les chunks problématiques (structure HTML)
3. Corriger manuellement dans les stores puis relancer

## Statistiques et métriques

Le système de validation fournit des statistiques détaillées :

```python
stats = pipeline.run(...)
glossary_stats = stats['glossary']

print(f"Termes appris: {glossary_stats['total_terms']}")
print(f"Termes validés: {glossary_stats['validated_terms']}")
print(f"Conflits résolus: {glossary_stats['conflicting_terms']}")
```

**Métriques de qualité** :
- **Taux de conflit** : `conflicting_terms / total_terms` (idéalement < 10%)
- **Taux de validation** : `validated_terms / total_terms` (idéalement > 80%)
- **Cohérence globale** : Basée sur la répartition des traductions

## Références

- [Glossary API](../src/ebook_translator/glossary.py)
- [GlossaryValidator](../src/ebook_translator/pipeline/glossary_validator.py)
- [TwoPhasePipeline](../src/ebook_translator/pipeline/two_phase_pipeline.py)
- [Tests](../tests/test_glossary_validator.py)
