# Changelog - Version 0.3.0

**Date** : 2025-10-20
**Titre** : Gestion d'erreurs robuste
**Auteur** : Claude Code

## 🎯 Objectif

Améliorer drastiquement la résilience du système de traduction face aux échecs LLM, notamment :
- Timeouts et rate limits
- Erreurs "Mismatch in fragment count"
- Traductions incomplètes ou mal formatées

## ✨ Nouvelles fonctionnalités

### 1. Système de retry avec backoff exponentiel

**Fichier** : [src/ebook_translator/llm.py](../src/ebook_translator/llm.py)

- ✅ Nouveau paramètre `max_retries` (défaut: 3)
- ✅ Nouveau paramètre `retry_delay` (défaut: 1.0s)
- ✅ Retry automatique pour timeout et rate limit
- ✅ Backoff exponentiel intelligent :
  - Timeout : ×2 (1s → 2s → 4s)
  - Rate limit : ×3 (1s → 3s → 9s)
- ✅ Logs détaillés avec émojis

**Avant** :
```python
❌ Erreur API: Timeout
[ERREUR: Timeout - Le serveur n'a pas répondu à temps]
```

**Après** :
```
⏱️ Timeout API (tentative 1/3): Request timed out
⏳ Attente de 1.0s avant nouvelle tentative...
⏱️ Timeout API (tentative 2/3): Request timed out
⏳ Attente de 2.0s avant nouvelle tentative...
✅ Requête LLM réussie après 3 tentative(s)
```

### 2. Messages d'erreur contextuels et actionnables

**Fichiers** :
- [src/ebook_translator/translation/parser.py](../src/ebook_translator/translation/parser.py)
- [src/ebook_translator/htmlpage/replacement.py](../src/ebook_translator/htmlpage/replacement.py)

Chaque erreur inclut maintenant :
- 📝 **Aperçu des données** problématiques
- 💡 **Causes possibles** de l'erreur
- 🔧 **Solutions** recommandées

**Exemple : Mismatch in fragment count**

```
❌ Mismatch in fragment count:
  • Expected: 3 fragments
  • Got: 2 segments in translation

📝 Original fragments (3):
  "Hello", "beautiful", "world"

🔄 Translation segments (2):
  "Bonjour", "monde magnifique"

💡 Causes possibles:
  • Le LLM a fusionné ou divisé des fragments
  • Des séparateurs '</>' manquants ou en trop
  • Le contenu contient des '</>' dans le texte original

🔧 Solutions:
  • Vérifiez les logs LLM pour voir la réponse brute
  • Relancez la traduction (retry automatique activé)
  • Ajustez le prompt pour mieux expliquer les séparateurs
```

### 3. Validation robuste et contextualisée

**Fichier** : [src/ebook_translator/translation/engine.py](../src/ebook_translator/translation/engine.py)

- ✅ Try/catch autour de l'application des traductions
- ✅ Logs détaillés avec contexte :
  - Nom du fichier source
  - TagKey concerné
  - Aperçu du texte original (100 premiers chars)
  - Aperçu de la traduction (100 premiers chars)

### 4. Affichage amélioré des erreurs

**Fichier** : [src/ebook_translator/worker.py](../src/ebook_translator/worker.py)

- ✅ Distinction entre erreurs de validation et erreurs inattendues
- ✅ Compteur d'erreurs en temps réel
- ✅ Formatage visuel avec bordures
- ✅ Résumé final
- ✅ Troncature intelligente des messages longs (>500 chars)

**Sortie exemple** :
```
Traduction des segments: 100%|████████| 50/50 [02:30<00:00]

============================================================
❌ ERREUR DE VALIDATION #1
============================================================
❌ Mismatch in fragment count:
  • Expected: 3 fragments
  • Got: 2 segments in translation
...
============================================================

⚠️  Traduction terminée avec 1 erreur(s).
   Consultez les logs dans le dossier 'logs/' pour plus de détails.
```

## 📚 Documentation

### Nouveau guide complet

**Fichier** : [docs/error_handling.md](error_handling.md)

Contenu :
- 📋 Vue d'ensemble du système
- 🔄 Explication du retry et backoff
- 📊 Tableaux des types d'erreurs
- 📝 Exemples de messages d'erreur
- 🔧 Guide de dépannage par symptôme
- ⚙️ Configuration recommandée
- 🔍 Analyse des logs

## 🧪 Tests

**Fichier** : [tests/test_error_handling.py](../tests/test_error_handling.py)

7 tests unitaires couvrant :
- ✅ Parsing avec marqueur manquant
- ✅ Détection d'erreur LLM
- ✅ Format invalide
- ✅ Mismatch de fragments
- ✅ Cas valides (standard, multilignes, avec séparateurs)

**Exécution** :
```bash
poetry run pytest tests/test_error_handling.py -v
```

**Résultat** :
```
7 passed in 0.73s
```

## 📈 Comparaison v0.2.0 → v0.3.0

| Aspect | v0.2.0 | v0.3.0 | Amélioration |
|--------|--------|--------|--------------|
| **Retry automatique** | ❌ Aucun | ✅ Backoff exponentiel | 🚀 Résilience |
| **Messages d'erreur** | ⚠️ Basiques | ✅ Contextuels + solutions | 📝 Debugging |
| **Validation** | ⚠️ Basique | ✅ Détaillée avec aperçu | 🔍 Précision |
| **Logs** | ⚠️ Peu exploitables | ✅ Contexte complet | 📊 Traçabilité |
| **Comportement** | ⚠️ Incohérent | ✅ Uniforme et prévisible | 🎯 Fiabilité |
| **Documentation** | ❌ Absente | ✅ Guide complet | 📚 Accessibilité |
| **Tests** | ❌ Aucun | ✅ 7 tests unitaires | 🧪 Qualité |

## 🔧 Migration

### Aucune action requise

Les nouveaux paramètres ont des valeurs par défaut et sont **100% rétrocompatibles**.

### Configuration personnalisée (optionnel)

```python
from ebook_translator import LLM, EpubTranslator, Language

# Augmenter les tentatives pour connexions instables
llm = LLM(
    model_name="deepseek-chat",
    url="https://api.deepseek.com",
    max_retries=5,      # Au lieu de 3 par défaut
    retry_delay=2.0,    # Au lieu de 1.0s par défaut
)

translator = EpubTranslator(llm, epub_path="book.epub")
translator.translate(
    target_language=Language.FRENCH,
    output_epub="book_fr.epub",
    max_concurrent=1,   # Réduire si rate limit fréquent
)
```

## 🎁 Bénéfices immédiats

### Pour les utilisateurs
- ✅ **Moins de traductions échouées** grâce au retry automatique
- ✅ **Meilleure compréhension** des erreurs avec messages détaillés
- ✅ **Debugging facilité** avec logs contextualisés
- ✅ **Gain de temps** : pas besoin de relancer manuellement

### Pour les développeurs
- ✅ **Tests unitaires** pour éviter les régressions
- ✅ **Documentation complète** pour maintenance future
- ✅ **Code robuste** avec gestion d'erreurs uniforme
- ✅ **Logs exploitables** pour support utilisateur

## 🚀 Prochaines étapes (Phase 2)

**Non implémentées** mais prévues :

1. **Stratégie de fallback configurable**
   - Option : garder le texte original
   - Option : marquer visuellement les zones non traduites
   - Option : remplacer par un placeholder

2. **Mode de reprise `--resume`**
   - Relancer uniquement les chunks échoués
   - Utiliser le cache existant pour éviter de retraduire

3. **Statistiques détaillées**
   - Nombre de chunks traduits/échoués
   - Temps moyen par chunk
   - Taux de réussite

4. **Rapport HTML des zones problématiques**
   - Vue interactive des erreurs
   - Comparaison original/traduction côte à côte
   - Export pour analyse

## 📝 Notes techniques

### Changements internes

1. **Ajout de `import time`** dans `llm.py` pour `time.sleep()`
2. **Ajout de `logger`** dans `engine.py` et `parser.py`
3. **Nouveau type `Optional[Exception]`** pour tracker `last_error`
4. **Nouveau compteur `errors_count`** dans `worker.py`

### Vérification des types

```bash
pyright src/ebook_translator/
```

**Résultat** : ✅ 0 errors, 0 warnings, 0 informations

### Couverture de tests

```bash
poetry run pytest --cov=src/ebook_translator --cov-report=html
```

Les nouveaux tests augmentent la couverture globale.

## 🙏 Crédits

Développé par Claude Code en réponse à la question utilisateur :
> "quoi faire lors d'un échec de traduction par le LLM comme un Mismatch in fragment count"

Cette version implémente la **Phase 1** du plan d'amélioration proposé.

## 📞 Support

Pour toute question ou problème :
1. Consultez [docs/error_handling.md](error_handling.md)
2. Vérifiez les logs dans `logs/`
3. Exécutez les tests : `poetry run pytest tests/test_error_handling.py -v`
4. Ouvrez une issue sur GitHub avec les logs complets
