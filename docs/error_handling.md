# Gestion des erreurs de traduction LLM

Ce document explique comment le système gère les échecs de traduction par le LLM, notamment les erreurs de type "Mismatch in fragment count".

## 📋 Table des matières

1. [Vue d'ensemble](#vue-densemble)
2. [Système de retry automatique](#système-de-retry-automatique)
3. [Types d'erreurs gérées](#types-derreurs-gérées)
4. [Messages d'erreur détaillés](#messages-derreur-détaillés)
5. [Configuration](#configuration)
6. [Dépannage](#dépannage)

## Vue d'ensemble

Le système de traduction inclut maintenant plusieurs mécanismes pour gérer gracieusement les échecs :

### ✅ Améliorations implémentées (Phase 1)

1. **Retry avec backoff exponentiel** : Les erreurs temporaires (timeout, rate limit) déclenchent automatiquement des nouvelles tentatives
2. **Validation pré-application** : Le nombre de fragments est vérifié avant d'appliquer les traductions
3. **Messages d'erreur contextuels** : Chaque erreur fournit des causes possibles et des solutions

## Système de retry automatique

### Fonctionnement

Le système effectue jusqu'à **3 tentatives** (configurable) pour chaque requête LLM qui échoue avec :
- **Timeout** : Délai de `1s, 2s, 4s` (backoff exponentiel ×2)
- **Rate Limit** : Délai de `1s, 3s, 9s` (backoff exponentiel ×3)

### Configuration

Dans [llm.py](../src/ebook_translator/llm.py) :

```python
llm = LLM(
    model_name="deepseek-chat",
    url="https://api.deepseek.com",
    max_retries=3,       # Nombre de tentatives (défaut: 3)
    retry_delay=1.0,     # Délai initial en secondes (défaut: 1.0)
)
```

### Logs produits

```
⏱️ Timeout API (tentative 1/3): Request timed out
⏳ Attente de 1.0s avant nouvelle tentative...
⏱️ Timeout API (tentative 2/3): Request timed out
⏳ Attente de 2.0s avant nouvelle tentative...
✅ Requête LLM réussie après 3 tentative(s) (1234 chars)
```

## Types d'erreurs gérées

### 1. Erreurs API temporaires (avec retry)

| Erreur | Retry | Délai | Description |
|--------|-------|-------|-------------|
| `APITimeoutError` | ✅ Oui | ×2 exponentiel | Le serveur n'a pas répondu à temps |
| `RateLimitError` | ✅ Oui | ×3 exponentiel | Trop de requêtes, limite de débit atteinte |

### 2. Erreurs API permanentes (sans retry)

| Erreur | Retry | Description |
|--------|-------|-------------|
| `APIError` | ❌ Non | Erreur API générique (clé invalide, etc.) |
| `OpenAIError` | ❌ Non | Erreur client OpenAI |
| `Exception` | ❌ Non | Erreur inattendue |

### 3. Erreurs de validation

| Erreur | Où | Description |
|--------|-----|-------------|
| Mismatch in fragment count | [replacement.py:82](../src/ebook_translator/htmlpage/replacement.py#L82) | Le LLM a retourné un nombre incorrect de fragments `</>` |
| Marqueur [=[END]=] manquant | [parser.py:50](../src/ebook_translator/translation/parser.py#L50) | La traduction est incomplète |
| Aucun segment trouvé | [parser.py:81](../src/ebook_translator/translation/parser.py#L81) | Le format de sortie LLM est invalide |

## Messages d'erreur détaillés

### Exemple : Mismatch in fragment count

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

### Exemple : Marqueur END manquant

```
❌ Traduction incomplète : le marqueur [=[END]=] est manquant.

📝 Aperçu de la sortie LLM:
<0/>Bonjour le monde
<1/>Ceci est un test...

💡 Causes possibles:
  • Le LLM a été interrompu avant la fin
  • La limite de tokens max_tokens est trop basse
  • Le LLM n'a pas suivi le format demandé

🔧 Solutions:
  • Augmentez max_tokens dans la config LLM
  • Réduisez la taille des chunks à traduire
  • Vérifiez le prompt de traduction
```

## Configuration

### Paramètres LLM recommandés

Pour éviter les erreurs de traduction incomplète :

```python
llm = LLM(
    model_name="deepseek-chat",
    url="https://api.deepseek.com",
    temperature=0.85,
    max_retries=3,
    retry_delay=1.0,
)
llm.max_tokens = 4000  # Augmenter si les traductions sont tronquées
```

### Paramètres de traduction

```python
translator.translate(
    target_language=Language.FRENCH,
    output_epub=output_epub,
    max_concurrent=2,  # Réduire si rate limit fréquent
    max_tokens=1500,   # Taille des chunks à traduire
)
```

## Dépannage

### Problème : Rate limit fréquent

**Symptômes** :
```
🚦 Limite de débit atteinte (tentative 1/3)
```

**Solutions** :
1. Réduire `max_concurrent` à 1 dans `translator.translate()`
2. Augmenter `retry_delay` dans `LLM()` à 2.0 ou 3.0 secondes
3. Vérifier votre quota API sur la plateforme

### Problème : Timeout systématique

**Symptômes** :
```
⏱️ Timeout API (tentative 3/3)
❌ Échec définitif après 3 tentatives
```

**Solutions** :
1. Vérifier votre connexion internet
2. Vérifier que l'URL de l'API est correcte
3. Réduire la taille des chunks avec `max_tokens` plus petit
4. Augmenter `max_retries` à 5

### Problème : Mismatch de fragments

**Symptômes** :
```
❌ Mismatch in fragment count: expected 5, got 4
```

**Solutions** :
1. **Vérifier les logs LLM** dans `logs/` pour voir la réponse brute
2. **Ajuster le prompt** dans [template/translate.jinja](../template/translate.jinja) :
   ```jinja
   IMPORTANT : Tu DOIS conserver EXACTEMENT le même nombre de balises '</>'
   que dans le texte original. Ne fusionne JAMAIS deux fragments.
   ```
3. **Réduire la température** du LLM (ex: `temperature=0.5`) pour des réponses plus déterministes
4. **Essayer un autre modèle** si le problème persiste

### Problème : Traduction incomplète

**Symptômes** :
```
❌ Traduction incomplète : le marqueur [=[END]=] est manquant
```

**Solutions** :
1. **Augmenter `max_tokens`** dans `LLM()` :
   ```python
   llm.max_tokens = 8000  # Au lieu de 4000
   ```
2. **Réduire la taille des chunks** dans `translator.translate()` :
   ```python
   max_tokens=1000  # Au lieu de 1500
   ```
3. **Vérifier le prompt** pour s'assurer qu'il demande bien le marqueur `[=[END]=]`

## Logs et debugging

### Localisation des logs

Tous les logs LLM sont enregistrés dans `logs/` avec un horodatage :
```
logs/
  2025-10-20T15-30-51.880739.txt
  2025-10-20T15-32-27.693400.txt
  ...
```

### Contenu d'un log

```
=== LLM REQUEST LOG ===
Timestamp : 2025-10-20T15-30-51.880739
Model     : deepseek-chat
Prompt len: 1234 chars
----------------------------------------

--- PROMPT ---
Tu es un traducteur professionnel...

--- CONTENT ---
<0/>Hello world
<1/>This is a test

--- RESPONSE ---
<0/>Bonjour le monde
<1/>Ceci est un test
[=[END]=]
```

### Analyser les logs en cas d'erreur

1. **Ouvrir le dernier log** dans `logs/`
2. **Vérifier la section RESPONSE** pour voir ce que le LLM a retourné
3. **Comparer avec le CONTENT** pour identifier les différences
4. **Compter les balises `</>`** pour détecter un mismatch

## Tests

Des tests unitaires sont disponibles dans [tests/test_error_handling.py](../tests/test_error_handling.py) :

```bash
# Exécuter les tests
poetry run pytest tests/test_error_handling.py -v

# Tests avec couverture
poetry run pytest tests/test_error_handling.py --cov=src/ebook_translator
```

## Prochaines améliorations (Phase 2)

Les améliorations suivantes sont prévues mais non encore implémentées :

- [ ] Stratégie de fallback configurable (garder l'original, marquer visuellement, etc.)
- [ ] Marqueurs visuels pour les zones non traduites
- [ ] Mode de reprise `--resume` pour relancer les chunks échoués
- [ ] Statistiques détaillées en fin de traduction
- [ ] Rapport HTML des zones problématiques

## Références

- [llm.py](../src/ebook_translator/llm.py) : Système de retry
- [parser.py](../src/ebook_translator/translation/parser.py) : Validation de sortie LLM
- [replacement.py](../src/ebook_translator/htmlpage/replacement.py) : Validation des fragments
- [engine.py](../src/ebook_translator/translation/engine.py) : Application des traductions
- [worker.py](../src/ebook_translator/worker.py) : Gestion des erreurs parallèles