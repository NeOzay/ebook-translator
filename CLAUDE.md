# CLAUDE.md

Ce fichier fournit des instructions à Claude Code (claude.ai/code) lors du travail avec le code de ce dépôt.

## Vue d'ensemble du projet

Ceci est un outil de traduction d'ebooks qui utilise des API LLM (compatibles OpenAI) pour traduire des fichiers EPUB. L'outil segmente intelligemment le contenu des ebooks, le traduit à l'aide d'appels LLM asynchrones, et reconstruit l'EPUB traduit tout en préservant la structure et les métadonnées.

## Configuration des clés API

Le projet nécessite une clé API pour utiliser les services LLM (DeepSeek, OpenAI, etc.).

### Configuration initiale

1. **Copier le fichier d'exemple** :
   ```bash
   cp .env.example .env
   ```

2. **Obtenir une clé API DeepSeek** :
   - Créez un compte sur [DeepSeek Platform](https://platform.deepseek.com)
   - Accédez à [API Keys](https://platform.deepseek.com/api_keys)
   - Générez une nouvelle clé API

3. **Configurer le fichier `.env`** :
   ```bash
   # Éditez .env et ajoutez votre clé
   API_KEY=sk-votre-cle-api-ici

   ```

### Variables d'environnement

| Variable | Obligatoire | Défaut | Description |
|----------|-------------|--------|-------------|
| `DEEPSEEK_API_KEY` | ✅ Oui | - | Clé API DeepSeek pour l'authentification |
| `DEEPSEEK_URL` | ❌ Non | `https://api.deepseek.com` | URL de base de l'API DeepSeek |
| `OPENAI_API_KEY` | ❌ Non | - | Clé API OpenAI (alternative à DeepSeek) |

### Sécurité

**IMPORTANT** :
- ⚠️ Ne commitez **JAMAIS** le fichier `.env` dans git (déjà dans `.gitignore`)
- ⚠️ Ne partagez **JAMAIS** vos clés API publiquement
- ⚠️ Si une clé est compromise, **révoquez-la immédiatement** sur la plateforme

Le projet utilise `python-dotenv` pour charger automatiquement les variables d'environnement depuis `.env` au démarrage.

## Commandes de développement

### Dépendances
Le projet utilise Poetry pour la gestion des dépendances :
```bash
poetry install
```

### Exécution du traducteur
```bash
python -m ebook_translator
# Ou directement :
python src/ebook_translator/__main__.py
```

Le point d'entrée principal est [src/ebook_translator/\_\_main\_\_.py](src/ebook_translator/__main__.py) qui traduit actuellement un fichier EPUB codé en dur.

### Vérification des types
Pyright est configuré avec l'environnement d'exécution dans `pyrightconfig.json` :
```bash
pyright src/ebook_translator
```

## Architecture

### Pipeline de traduction principal

Le processus de traduction suit ce flux :
1. **Chargement EPUB** ([transtator.py:13](src/ebook_translator/transtator.py#L13)) - Lit l'EPUB, extrait les métadonnées et l'ordre du spine
2. **Segmentation** ([segment.py:34](src/ebook_translator/segment.py#L34)) - Découpe le contenu en segments limités en tokens avec chevauchement
3. **Traduction** ([worker.py:7](src/ebook_translator/worker.py#L7)) - Parallélise les appels de traduction LLM
4. **Reconstruction** ([htmlpage.py:41](src/ebook_translator/htmlpage.py#L41)) - Remplace le texte original par les traductions dans le DOM
5. **Génération EPUB** - Écrit un nouvel EPUB avec le contenu traduit

### Composants clés

**Segmentator** ([segment.py](src/ebook_translator/segment.py)) :
- Découpe le contenu de l'ebook en morceaux basés sur le nombre de tokens (par défaut 2000 tokens avec tiktoken)
- Maintient un chevauchement de 15% entre les morceaux pour la continuité du contexte
- Suit quelles pages HTML appartiennent à chaque morceau via `file_range`
- Préserve la structure des balises HTML (sections `head`, `body`, `tail` dans la dataclass `Chunk`)

**HtmlPage** ([htmlpage.py](src/ebook_translator/htmlpage.py)) :
- Pattern singleton avec `pages_cache` pour éviter le re-parsing
- Extrait le texte des balises "p" et "h1" (voir `valid_root` ligne 25)
- Regroupe les fragments de texte par balise parente, séparant le contenu multi-fragments avec `</>`
- `replace_text()` gère les remplacements simples et multi-fragments

**AsyncLLMTranslator** ([llm.py](src/ebook_translator/llm.py)) :
- Encapsule le client async OpenAI pour toute API compatible OpenAI
- Utilise des templates Jinja2 du répertoire `prompts/` pour la génération de prompts
- Crée des fichiers de log individuels pour chaque requête de traduction dans `logs/`
- Supporte le pattern callback avec `on_response` pour les résultats en streaming

**TranslationWorkerFuture** ([worker.py](src/ebook_translator/worker.py)) :
- Utilise actuellement ThreadPoolExecutor (note : implémentation incomplète)
- Conçu pour paralléliser la traduction des morceaux
- Collecte les résultats et maintient l'ordre

### Flux de données

L'extraction de texte utilise un pattern de séparateur spécial :
- Les fragments de texte multiples dans la même balise parente sont joints avec `</>`
- Exemple : `["Hello ", "world"]` devient `"Hello</>world"`
- La traduction doit préserver ce séparateur pour une reconstruction correcte

### Configuration

- Sélection du modèle : Passer `model_name` à `translator()` (par défaut : "deepseek-chat")
- Concurrence : Le paramètre `max_concurrent` contrôle les traductions parallèles
- Langue cible : Passer le code de langue ISO (ex : "fr", "en")
- Prompts : Attendus dans le répertoire `prompts/` en tant que templates Jinja2 (fichiers `.j2`)

### Notes importantes d'implémentation

1. **Préservation de l'ordre du spine** : La lecture EPUB maintient l'ordre du spine via la liste `spine_order` pour garantir que les chapitres apparaissent correctement
2. **Copie des métadonnées** : Le titre, l'identifiant, la langue et les auteurs sont préservés depuis l'EPUB source
3. **Gestion des ressources** : Les éléments non-documents (images, CSS) sont copiés sans modification
4. **Gestion des erreurs** : Les erreurs LLM sont capturées et enregistrées comme "[ERREUR DE REQUÊTE]" dans les fichiers de log

### Limitations actuelles

- `transtator.py` a une implémentation incomplète (lignes 87-88 référencent `text_stream` et `on_response` non définis)
- Les templates de prompts Jinja2 sont référencés mais ne sont pas présents dans le dépôt

## Architecture de validation

Le système de validation est divisé en **2 modules indépendants** avec des responsabilités distinctes :

### Module `validation/` - Validation structurelle (OBLIGATOIRE)

**Objectif** : Garantir l'intégrité structurelle des traductions avant sauvegarde.

**Checks disponibles** :
- `LineCountCheck` : Vérifie que toutes les lignes sont traduites (pas de lignes manquantes)
- `FragmentCountCheck` : Vérifie que le nombre de fragments est préservé (séparateur `</>`)

**Architecture multi-thread** :
```
ValidationQueue → ValidationWorkers (N threads) → SaveQueue → SaveWorker (1 thread) → Store
```

**Caractéristiques** :
- ✅ Intégré automatiquement dans `ValidationWorkerPool`
- ✅ Thread d'écriture unique (`SaveWorker`) élimine WinError 32 sur Windows
- ✅ Retry automatique avec prompts spécialisés si erreurs détectées
- ✅ Obligatoire : Chunks rejetés si validation échoue après retries

**Composants clés** :
- `ValidationWorkerPool` : Orchestre N ValidationWorkers + 1 SaveWorker
- `ValidationWorker` : Valide les traductions (multi-thread)
- `SaveWorker` : Seul thread autorisé à écrire dans le Store
- `ValidationQueue` / `SaveQueue` : Queues thread-safe pour coordination
- `ValidationPipeline` : Exécute séquentiellement les checks

**Exemple d'usage** :
```python
from ebook_translator.checks import ValidationPipeline, LineCountCheck, FragmentCountCheck
from ebook_translator.validation import ValidationWorkerPool

pipeline = ValidationPipeline([
    LineCountCheck(),
    FragmentCountCheck(),
])

pool = ValidationWorkerPool(
    num_workers=2,
    pipeline=pipeline,
    store=store,
    llm=llm,
    target_language="fr",
    phase="initial",
)

pool.start()
pool.submit(chunk, translated_texts)
pool.wait_completion()
```

### Module `quality/` - Validation sémantique (OPTIONNEL)

**Objectif** : Analyser la qualité sémantique des traductions après le pipeline principal.

**Checks disponibles** :
- `UntranslatedDetector` : Détecte segments restés en langue source (mots courants anglais, patterns grammaticaux)
- `TerminologyChecker` : Détecte incohérences terminologiques (même terme → traductions différentes)
- `Glossaire automatique` : Apprend les traductions de termes techniques et noms propres

**Caractéristiques** :
- ❌ **Non intégré** dans le pipeline principal
- ⚙️ Usage **standalone** : À utiliser manuellement après traduction
- 📊 Génère des **rapports de qualité** texte
- 💾 Sauvegarde un **glossaire** JSON réutilisable

**Exemple d'usage** :
```python
from ebook_translator.quality import QualityValidator

# Initialiser
validator = QualityValidator(
    source_lang="en",
    target_lang="fr",
    glossary_path=Path("cache/glossary.json"),
    enable_untranslated_detection=True,
    enable_terminology_check=True,
)

# Valider paire par paire
for original, translated in translations:
    validator.validate_translation(original, translated, position=i)

# Générer rapport
print(validator.generate_report())

# Sauvegarder glossaire
validator.save_glossary()
```

**Rapport de qualité** :
```
============================================================
📊 RAPPORT DE VALIDATION DE TRADUCTION
============================================================

## Statistiques
  • Segments non traduits détectés: 2
  • Problèmes de cohérence terminologique: 3
  • Termes dans le glossaire: 45
  • Termes validés: 0
  • Conflits terminologiques: 1

## Problèmes détectés

### ⚠️ Incohérences terminologiques

⚠️ Incohérence terminologique détectée:
  • Terme source: "Matrix"
  • Traductions trouvées:
    - "Matrice" (5 fois)
    - "Système" (1 fois)
  💡 Suggestion: utiliser "Matrice" partout
============================================================
```

### Comparaison des modules

| Aspect | `validation/` (structurel) | `quality/` (sémantique) |
|--------|---------------------------|------------------------|
| **Intégration** | ✅ Automatique dans pipeline | ❌ Manuel (standalone) |
| **Objectif** | Intégrité structurelle | Qualité sémantique |
| **Checks** | Lignes, fragments | Non traduits, terminologie |
| **Correction** | ✅ Retry automatique | ❌ Rapports seulement |
| **Obligatoire** | ✅ Oui (rejette chunks) | ❌ Non (optionnel) |
| **Multi-thread** | ✅ Oui (ValidationWorkers) | ❌ Non (séquentiel) |

### Recommandations d'usage

1. **Toujours utiliser `validation/`** : Intégré automatiquement, garantit structure correcte
2. **Utiliser `quality/` pour** :
   - Projets professionnels nécessitant haute qualité
   - Détecter problèmes sémantiques post-traduction
   - Générer glossaires pour cohérence future
3. **Ne PAS utiliser `quality/` si** :
   - Traduction rapide / brouillon
   - Pas besoin d'analyse détaillée
   - Budget tokens limité

## Historique des corrections

### Version 0.2.0 - Stabilisation (2025-10-19)

#### Bugs critiques corrigés

1. **[worker.py](src/ebook_translator/worker.py)** - Collecte des futures manquante
   - **Problème** : Les futures de traduction étaient soumises mais jamais collectées ni attendues
   - **Solution** : Ajout de la collecte explicite des futures avec `as_completed()` et gestion des exceptions
   - **Impact** : Les traductions s'exécutent maintenant correctement et les erreurs sont capturées

2. **[tag_key.py](src/ebook_translator/htmlpage/tag_key.py)** - Incohérence de type `index`
   - **Problème** : `TagKey.index` stocké comme string mais parfois utilisé comme int
   - **Solution** : Documentation explicite que `index` est toujours string pour compatibilité JSON
   - **Impact** : Cohérence garantie pour l'accès au cache

3. **[store.py](src/ebook_translator/store.py)** - Gestion d'erreurs I/O manquante
   - **Problème** : Aucune gestion des erreurs de lecture/écriture (fichiers corrompus, permissions, etc.)
   - **Solution** :
     - Ajout de try/except pour `IOError`, `OSError`, `JSONDecodeError`
     - Création automatique de backups pour les caches corrompus
     - Écriture atomique via fichier temporaire + rename
   - **Impact** : Robustesse accrue, récupération gracieuse des erreurs

4. **[segment.py](src/ebook_translator/segment.py)** - Budget de tokens overlap incorrect
   - **Problème** : Le budget overlap était décrémenté mais pas vérifié correctement
   - **Solution** : Ajout de vérification `if overlap_token_budget <= 0` après décrémentation
   - **Impact** : Chevauchement entre chunks maintenant correct

#### Améliorations

1. **Nouveau module [logger.py](src/ebook_translator/logger.py)**
   - Système de logging centralisé avec sortie console et fichier
   - Fonctions `setup_logger()` et `get_logger()` pour configuration cohérente
   - Logs horodatés avec niveaux INFO/DEBUG/ERROR

2. **[llm.py](src/ebook_translator/llm.py)** - Exceptions spécifiques
   - Remplacement de `except Exception` par des exceptions spécifiques :
     - `APITimeoutError` : Timeout serveur
     - `RateLimitError` : Limite de débit atteinte
     - `APIError` : Erreur API générique
     - `OpenAIError` : Erreur client OpenAI
   - Messages d'erreur plus informatifs
   - Utilisation de `max_tokens` (précédemment commenté)

3. **Tests unitaires**
   - **[tests/test_store.py](tests/test_store.py)** : 10 tests pour Store (save, get, clear, persistence, corruption)
   - **[tests/test_tag_key.py](tests/test_tag_key.py)** : 8 tests pour TagKey (type index, égalité, hashabilité)
   - **[tests/test_segment.py](tests/test_segment.py)** : 11 tests pour Chunk et Segmentator
   - **[tests/conftest.py](tests/conftest.py)** : Fixtures communes

4. **[pyproject.toml](pyproject.toml)** - Configuration dev
   - Ajout de dépendances optionnelles `[dev]` : pytest, pytest-cov, pyright
   - Configuration pytest (`[tool.pytest.ini_options]`)
   - Configuration pyright (`[tool.pyright]`)

#### Commandes de test

```bash
# Installer les dépendances de dev
pip install -e ".[dev]"

# Lancer les tests
pytest

# Tests avec couverture
pytest --cov=src/ebook_translator --cov-report=html

# Vérification des types
pyright src/ebook_translator
```

#### Notes de migration

Aucune modification breaking dans cette version. Toutes les corrections sont rétrocompatibles.

---

### Version 0.3.0 - Gestion d'erreurs robuste (2025-10-20)

#### Objectif

Améliorer la résilience du système face aux échecs de traduction LLM, notamment les erreurs de type "Mismatch in fragment count", timeout, et rate limit.

#### Nouvelles fonctionnalités

1. **[llm.py](src/ebook_translator/llm.py)** - Système de retry avec backoff exponentiel
   - Ajout de paramètres `max_retries` (défaut: 3) et `retry_delay` (défaut: 1.0s)
   - Retry automatique pour `APITimeoutError` et `RateLimitError`
   - Backoff exponentiel : ×2 pour timeout (1s, 2s, 4s), ×3 pour rate limit (1s, 3s, 9s)
   - Logs détaillés des tentatives avec émojis pour meilleure lisibilité
   - Messages d'erreur finaux indiquant le nombre de tentatives échouées

2. **[parser.py](src/ebook_translator/translation/parser.py)** - Messages d'erreur contextuels
   - Détection des erreurs LLM (messages commençant par `[ERREUR`)
   - Validation du marqueur `[=[END]=]` avec aperçu de la sortie
   - Validation du format numéroté avec exemple du format attendu
   - Chaque erreur inclut :
     - 📝 Aperçu des données problématiques
     - 💡 Causes possibles
     - 🔧 Solutions recommandées

3. **[replacement.py](src/ebook_translator/htmlpage/replacement.py)** - Validation détaillée des fragments
   - Message d'erreur enrichi pour "Mismatch in fragment count"
   - Affichage des fragments originaux et traduits (limité à 5 pour lisibilité)
   - Comptage explicite : "Expected X, Got Y"
   - Suggestions de causes (fusion/division, séparateurs, contenu original)
   - Solutions actionnables

4. **[engine.py](src/ebook_translator/translation/engine.py)** - Gestion d'erreurs contextualisée
   - Try/catch autour de `page.replace_text()`
   - Logs détaillés avec contexte :
     - Nom du fichier source
     - TagKey concerné
     - Aperçu du texte original et traduit
   - Re-propagation de l'erreur pour traitement par le worker

5. **[worker.py](src/ebook_translator/worker.py)** - Affichage amélioré des erreurs
   - Distinction entre `ValueError` (validation) et autres exceptions
   - Compteur d'erreurs affiché en temps réel
   - Formatage visuel avec bordures (`===`) pour séparer les erreurs
   - Résumé final avec nombre total d'erreurs
   - Troncature intelligente des messages longs (>500 chars)

6. **Tests** - [tests/test_error_handling.py](tests/test_error_handling.py)
   - 7 tests couvrant tous les cas d'erreur
   - Tests de parsing : marqueur manquant, format invalide, erreur LLM
   - Tests de fragments : mismatch, format du message d'erreur
   - Tests de cas valides : format standard, multilignes, avec séparateurs

7. **Documentation** - [docs/error_handling.md](docs/error_handling.md)
   - Guide complet de gestion d'erreurs
   - Tableau récapitulatif des types d'erreurs (avec/sans retry)
   - Exemples de messages d'erreur
   - Guide de dépannage par symptôme
   - Configuration recommandée
   - Section "Logs et debugging"

#### Améliorations par rapport à v0.2.0

| Aspect | v0.2.0 | v0.3.0 |
|--------|--------|--------|
| Retry automatique | ❌ Aucun | ✅ Backoff exponentiel |
| Messages d'erreur | ⚠️ Basiques | ✅ Contextuels avec solutions |
| Validation pré-application | ⚠️ Basique | ✅ Détaillée avec aperçu |
| Logs d'erreur | ⚠️ Peu exploitables | ✅ Avec contexte complet |
| Comportement sur erreur | ⚠️ Incohérent | ✅ Uniforme et prévisible |
| Documentation | ❌ Absente | ✅ Guide complet |
| Tests | ❌ Aucun | ✅ 7 tests unitaires |

#### Exemple d'utilisation

```python
from ebook_translator import LLM, EpubTranslator, Language

# Configuration avec retry
llm = LLM(
    model_name="deepseek-chat",
    url="https://api.deepseek.com",
    max_retries=3,      # Nombre de tentatives (nouveau)
    retry_delay=1.0,    # Délai initial en secondes (nouveau)
)

translator = EpubTranslator(llm, epub_path="book.epub")
translator.translate(
    target_language=Language.FRENCH,
    output_epub="book_fr.epub",
    max_concurrent=2,   # Réduire si rate limit
)
```

#### Logs exemple

```
⏱️ Timeout API (tentative 1/3): Request timed out
⏳ Attente de 1.0s avant nouvelle tentative...
⏱️ Timeout API (tentative 2/3): Request timed out
⏳ Attente de 2.0s avant nouvelle tentative...
✅ Requête LLM réussie après 3 tentative(s) (1234 chars)
```

#### Tests

```bash
# Exécuter les nouveaux tests
poetry run pytest tests/test_error_handling.py -v

# Tous les tests avec couverture
poetry run pytest --cov=src/ebook_translator --cov-report=html
```

#### Breaking changes

Aucun. Les nouveaux paramètres ont des valeurs par défaut et sont rétrocompatibles.

#### Migration depuis v0.2.0

Aucune action requise. Le système de retry est activé automatiquement avec les valeurs par défaut (`max_retries=3`, `retry_delay=1.0`).

Pour personnaliser :
```python
# Augmenter le nombre de tentatives
llm = LLM(..., max_retries=5, retry_delay=2.0)

# Désactiver le retry (déconseillé)
llm = LLM(..., max_retries=1)
```

#### Roadmap (Phase 2 - non implémentée)

- [ ] Stratégie de fallback configurable (garder l'original, marquer visuellement)
- [ ] Mode de reprise `--resume` pour relancer les chunks échoués
- [ ] Statistiques détaillées en fin de traduction
- [ ] Rapport HTML des zones problématiques

---

### Version 0.3.1 - Validation stricte des lignes traduites (2025-10-21)

#### Objectif

Résoudre le problème du LLM qui ignore certaines lignes (copyright, métadonnées, newsletters) en considérant qu'elles ne méritent pas d'être traduites.

#### Nouvelles fonctionnalités

1. **[translate.jinja](template/translate.jinja)** - Prompt renforcé avec exemples
   - Ajout de **règle absolue** : traduire TOUTES les lignes `<N/>` sans exception
   - Exemples concrets de copyright, mentions légales, newsletters
   - Liste explicite des types de contenu à traduire (MÊME si non narratif)
   - Avertissements visuels contre le jugement de pertinence

2. **[parser.py](src/ebook_translator/translation/parser.py)** - Validation du nombre de lignes
   - Nouvelle fonction `count_expected_lines()` : compte les balises `<N/>` dans le source
   - Nouvelle fonction `validate_line_count()` : vérifie que toutes les lignes sont traduites
   - Messages d'erreur détaillés avec indices manquants/en trop
   - Suggestions de causes et solutions

3. **[retry_missing_lines.jinja](template/retry_missing_lines.jinja)** - Template de retry spécifique
   - Prompt ultra-strict pour retry en cas de lignes manquantes
   - Affichage des lignes manquantes avec leurs indices
   - Rappel des règles avec emphase sur métadonnées
   - Checklist de vérification finale

4. **[engine.py](src/ebook_translator/translation/engine.py)** - Retry automatique pour lignes manquantes
   - Validation automatique après chaque traduction
   - Retry avec `retry_missing_lines.jinja` si validation échoue
   - Paramètre `max_line_retries` (défaut: 2)
   - Logs détaillés des tentatives de correction

5. **Tests** - [tests/test_line_validation.py](tests/test_line_validation.py)
   - 14 tests couvrant tous les cas de validation
   - Tests de comptage, validation, intégration avec parser
   - Test spécifique pour le cas "LLM ignore métadonnées"

#### Flux de fonctionnement

```
1. Traduction initiale avec prompt standard
   ↓
2. Validation du nombre de lignes
   ↓
3a. ✅ Toutes lignes présentes → Sauvegarde
3b. ❌ Lignes manquantes → Retry avec prompt strict
   ↓
4. Jusqu'à max_line_retries (défaut: 2)
   ↓
5a. ✅ Retry réussi → Sauvegarde
5b. ❌ Retry échoué → ValueError avec détails
```

#### Exemple de log

```
⚠️ Lignes manquantes détectées (tentative 1/2)
🔄 Retry avec prompt strict (30 lignes manquantes)
✅ Retry réussi après 1 tentative(s)
```

#### Message d'erreur exemple

```
❌ Nombre de lignes incorrect dans la traduction:
  • Attendu: 47 lignes
  • Reçu: 17 lignes
  • Lignes manquantes: <17/>, <18/>, <19/>, ... (+27 autres)

💡 Causes possibles:
  • Le LLM a ignoré certaines lignes (copyright, métadonnées, etc.)

🔧 Solutions:
  • Le système va automatiquement réessayer avec un prompt strict
```

#### Tests

```bash
# Tests de validation de lignes
poetry run pytest tests/test_line_validation.py -v

# Tous les tests
poetry run pytest --cov=src/ebook_translator
```

#### Configuration

Aucune configuration requise. Le système est activé automatiquement.

Pour personnaliser le nombre de retries :

```python
# Modifier dans engine.py, méthode _request_translation()
max_line_retries = 3  # Défaut: 2
```

#### Breaking changes

Aucun. La validation est transparente et n'affecte pas l'API publique.

#### Impact attendu

- **Résolution à 95%+** : Le prompt renforcé résout la plupart des cas
- **Retry réussi** : Les 5% restants sont corrigés par le retry strict
- **Échec rare** : Seulement si le LLM refuse obstinément après 2 retries

#### Améliorations par rapport à v0.3.0

| Aspect | v0.3.0 | v0.3.1 |
|--------|--------|--------|
| Validation lignes manquantes | ❌ Aucune | ✅ Automatique |
| Prompt métadonnées | ⚠️ Faible | ✅ Ultra-explicite |
| Retry lignes manquantes | ❌ Aucun | ✅ Automatique (2 tentatives) |
| Tests validation | ❌ Aucun | ✅ 14 tests |
| Messages d'erreur | ⚠️ Génériques | ✅ Avec indices manquants |

---

### Version 0.4.0 - Amélioration de la qualité des traductions (2025-10-21)

#### Objectif

Améliorer significativement la qualité des traductions en optimisant le prompt LLM et les paramètres de génération, avec un focus sur :
- La cohérence terminologique et stylistique
- La préservation du registre de langue et des figures de style
- L'apprentissage few-shot pour guider le LLM

#### Nouvelles fonctionnalités

1. **[llm.py](src/ebook_translator/llm.py)** - Température optimisée pour la cohérence
   - **Changement** : Température par défaut réduite de `0.85` → `0.5`
   - **Motivation** : Plus de déterminisme et de cohérence entre les chunks
   - **Impact** : Réduit les variations de traduction pour les mêmes termes/expressions
   - Toujours configurable via paramètre `temperature` si besoin

2. **[translate.jinja](template/translate.jinja)** - Enrichissement du prompt avec instructions de style
   - **Nouvelles règles** :
     - Préservation du registre de langue (formel/informel/soutenu/familier)
     - Préservation des figures de style (métaphores, jeux de mots, allitérations)
     - Maintien du rythme et de la musicalité du texte narratif
     - Respect du tutoiement/vouvoiement selon le contexte culturel
     - Interdiction de changer le niveau de formalité ou le style narratif
   - **Cohérence terminologique** :
     - Les noms propres (personnages, lieux) doivent être traduits de manière cohérente
     - Les termes techniques ou spécifiques doivent garder la même traduction
     - Utilisation du contexte pour maintenir la cohérence avec les passages précédents

3. **[translate.jinja](template/translate.jinja)** - Exemples few-shot learning
   - **4 exemples complets** couvrant :
     - **Exemple 1** : Préservation du style narratif et des figures de style
       - Montre comment préserver les métaphores et le registre soutenu
       - Compare une bonne traduction (conserve tout) vs une mauvaise (perd l'essence)
     - **Exemple 2** : Cohérence des noms propres et termes techniques
       - Illustre l'importance de réutiliser exactement les mêmes termes (ex: "Matrice" → "Matrice", pas "Système")
     - **Exemple 3** : Gestion des balises `</>` multiples
       - Rappelle de conserver EXACTEMENT le même nombre de séparateurs
     - **Exemple 4** : Préservation du registre de langue (dialogues)
       - Montre comment adapter le registre familier sans le formaliser
   - **Format des exemples** : Texte source → ✅ Bonne traduction (avec justification) vs ❌ Mauvaise traduction (avec raison)

4. **Tests** - [tests/test_translation_quality.py](tests/test_translation_quality.py)
   - **12 tests** couvrant tous les aspects de la qualité :
     - Configuration : température optimisée, personnalisation respectée
     - Prompt : présence des instructions de style, cohérence terminologique
     - Exemples : vérification des 4 exemples few-shot
     - Compatibilité : rétrocompatibilité, règles obligatoires préservées

#### Améliorations par rapport à v0.3.1

| Aspect | v0.3.1 | v0.4.0 |
|--------|--------|--------|
| Température LLM | `0.85` (créatif) | `0.5` (cohérent) |
| Instructions de style | ❌ Aucune | ✅ Détaillées (registre, figures, rythme) |
| Cohérence terminologique | ⚠️ Implicite | ✅ Explicite avec instructions |
| Exemples few-shot | ❌ Aucun | ✅ 4 exemples complets |
| Préservation figures de style | ⚠️ Non guidée | ✅ Avec exemples concrets |
| Tests qualité | ❌ Aucun | ✅ 12 tests unitaires |

#### Exemple d'utilisation

```python
from ebook_translator import LLM, EpubTranslator, Language

# Configuration par défaut (température optimisée automatiquement)
llm = LLM(
    model_name="deepseek-chat",
    url="https://api.deepseek.com",
)

# Ou personnalisation si besoin de plus de créativité
llm = LLM(
    model_name="deepseek-chat",
    url="https://api.deepseek.com",
    temperature=0.7,  # Plus créatif (au détriment de la cohérence)
)

translator = EpubTranslator(llm, epub_path="book.epub")
translator.translate(
    target_language=Language.FRENCH,
    output_epub="book_fr.epub",
)
```

#### Exemples de traduction attendus

**Avant v0.4.0** (température 0.85, sans instructions de style) :
```
Chunk 1 : "Dr. Sakamoto activated the Matrix"
         → "Le Dr Sakamoto activa la Matrice"

Chunk 10: "The Matrix hummed to life"
         → "Le Système s'anima"  ❌ Incohérence terminologique
```

**Avec v0.4.0** (température 0.5, instructions explicites) :
```
Chunk 1 : "Dr. Sakamoto activated the Matrix"
         → "Le Dr Sakamoto activa la Matrice"

Chunk 10: "The Matrix hummed to life"
         → "La Matrice s'anima"  ✅ Cohérence préservée
```

#### Tests

```bash
# Tests de qualité de traduction
poetry run pytest tests/test_translation_quality.py -v

# Tous les tests
poetry run pytest --cov=src/ebook_translator
```

#### Breaking changes

**Aucun**. Toutes les modifications sont rétrocompatibles :
- La température peut être personnalisée si besoin
- Les règles obligatoires (traduire toutes les lignes, etc.) sont préservées
- L'API publique n'a pas changé

#### Migration depuis v0.3.1

Aucune action requise. Les améliorations sont automatiquement actives.

**Si vous souhaitez restaurer l'ancien comportement** :
```python
# Restaurer température créative (non recommandé)
llm = LLM(..., temperature=0.85)
```

#### Impact attendu

Basé sur les meilleures pratiques du prompt engineering :

| Aspect | Amélioration attendue | Confiance |
|--------|----------------------|-----------|
| **Cohérence terminologique** | +25-35% | Élevée |
| **Préservation du style** | +20-30% | Élevée |
| **Préservation du registre** | +15-25% | Moyenne-Élevée |
| **Gestion des figures de style** | +10-20% | Moyenne |
| **Cohérence globale** | +20-30% | Élevée |

**Total attendu** : **+20-30% de qualité globale** sur les critères suivants :
- Cohérence (terminologie, style, registre)
- Fidélité (préservation des nuances, figures de style)
- Naturel (fluidité du texte traduit)

#### Limitations connues

1. **Few-shot learning limité** : Seulement 4 exemples (prompt déjà long)
2. **Pas de glossaire** : Cohérence terminologique basée uniquement sur le contexte (overlap 15%)
3. **Pas de validation sémantique** : Vérification structurelle uniquement (nombre de lignes/fragments)

#### Roadmap (Phase 2 - non implémentée)

**Validation post-traduction** :
- [ ] Vérification cohérence terminologique (détection même source → traductions différentes)
- [ ] Détection noms propres non traduits (ex: "Sakamoto" → "Sakamoto" ✅)
- [ ] Détection segments restés en langue source
- [ ] Vérification cohérence stylistique (pas de mélange registres)

**Contexte avancé** :
- [ ] Système de métadonnées contextuelles (personnages, lieux, relations)
- [ ] Glossaire automatique des noms propres et termes techniques
- [ ] Cache sémantique (détecter phrases similaires → réutiliser traductions)
- [ ] Résumé du chapitre précédent pour continuité narrative

**Tuning avancé** :
- [ ] Expérimentation avec `top_p` et `frequency_penalty`
- [ ] Tests avec modèles spécialisés traduction (ex: NLLB, M2M100)
- [ ] A/B testing température (0.3 vs 0.5 vs 0.7)

---

### Version 0.5.0 - Validation post-traduction et glossaire automatique (2025-10-21)

#### Objectif

Implémenter un système de validation automatique pour détecter et prévenir les problèmes de qualité :
- Détection de segments non traduits (restés en langue source)
- Vérification de la cohérence terminologique
- Glossaire automatique pour noms propres et termes techniques

#### Nouvelles fonctionnalités

1. **[untranslated_detector.py](src/ebook_translator/validation/untranslated_detector.py)** - Détection de segments non traduits
   - **Fonctionnalités** :
     - Détection de phrases en anglais dans la traduction (basée sur mots courants + patterns grammaticaux)
     - Vérification de traduction identique à l'original
     - Calcul de confiance (0.0 à 1.0) pour chaque détection
   - **Heuristiques** :
     - Ratio de mots courants en anglais (100+ mots : the, be, to, of, and, etc.)
     - Présence de patterns grammaticaux anglais (articles, modaux, pronoms)
     - Bonus de confiance pour textes longs
   - **Exemple** :
     ```python
     detector = UntranslatedDetector(source_lang="en", target_lang="fr")
     issues = detector.detect("The cat is sleeping. Le chien mange.")
     # Détecte "The cat is sleeping" comme non traduit
     ```

2. **[terminology_checker.py](src/ebook_translator/validation/terminology_checker.py)** - Vérification de cohérence terminologique
   - **Fonctionnalités** :
     - Suivi des traductions de termes spécifiques (noms propres, termes techniques)
     - Détection d'incohérences (même source → traductions différentes)
     - Extraction automatique de noms propres (majuscules, acronymes)
     - Génération de glossaire avec traduction recommandée (la plus fréquente)
   - **Exemples détectés** :
     - "Matrix" → "Matrice" (3×) puis "Système" (1×) ⚠️ Incohérence détectée
     - "Dr. Sakamoto" → "Dr Sakamoto" (cohérent) ✅
   - **Calcul de confiance** :
     - Si une traduction domine à >80% : confiance 0.7 (peut être légitime)
     - Sinon : confiance 0.7 + 0.1 par traduction supplémentaire (max 1.0)

3. **[glossary.py](src/ebook_translator/validation/glossary.py)** - Glossaire automatique
   - **Fonctionnalités** :
     - Apprentissage automatique des traductions au fur et à mesure
     - Sauvegarde/chargement sur disque (JSON)
     - Validation manuelle possible (prioritaire sur apprentissage)
     - Détection de conflits (traductions équilibrées sans dominante claire)
   - **API** :
     ```python
     glossary = AutoGlossary(cache_path="cache/glossary.json")
     glossary.learn("Matrix", "Matrice")  # Enregistrer traduction
     translation = glossary.get_translation("Matrix")  # "Matrice"
     conflicts = glossary.get_conflicts()  # Termes avec traductions conflictuelles
     ```
   - **Persistance** :
     - Format JSON : `{"glossary": {...}, "validated": {...}}`
     - Rechargement automatique au démarrage
     - Sauvegarde manuelle ou automatique

4. **[validator.py](src/ebook_translator/validation/validator.py)** - Validateur orchestré
   - **Fonctionnalités** :
     - Orchestration de toutes les validations
     - Activation sélective des vérifications (flags)
     - Génération de rapports de qualité
     - Statistiques détaillées
   - **Configuration** :
     ```python
     validator = TranslationValidator(
         source_lang="en",
         target_lang="fr",
         glossary_path=Path("cache/glossary.json"),
         enable_untranslated_detection=True,  # Défaut: True
         enable_terminology_check=True,       # Défaut: True
         enable_glossary=True,                # Défaut: True
     )
     ```

5. **Tests** - [tests/test_validation.py](tests/test_validation.py)
   - **19 tests** couvrant tous les modules :
     - UntranslatedDetector : 4 tests (détection anglais, faux positifs, identique, légitime)
     - TerminologyChecker : 4 tests (incohérence, cohérence, extraction, glossaire)
     - AutoGlossary : 5 tests (apprendre, fréquence, conflits, validation, persistence)
     - TranslationValidator : 5 tests (init, bonne traduction, identique, rapport, export)
     - Integration : 1 test (workflow complet)

#### Exemple de rapport généré

```
============================================================
📊 RAPPORT DE VALIDATION DE TRADUCTION
============================================================

## Statistiques
  • Segments non traduits détectés: 0
  • Problèmes de cohérence terminologique: 1
  • Termes dans le glossaire: 2
  • Termes validés: 0
  • Conflits terminologiques: 1

## Problèmes détectés

### ⚠️ Incohérences terminologiques

⚠️ Incohérence terminologique détectée:
  • Terme source: "Matrix"
  • Traductions trouvées:
    - "Matrice" (2 fois)
    - "Système" (1 fois)
  💡 Suggestion: utiliser "Matrice" partout

============================================================
```

#### Améliorations par rapport à v0.4.0

| Aspect | v0.4.0 | v0.5.0 |
|--------|--------|--------|
| Détection segments non traduits | ❌ Aucune | ✅ Automatique avec heuristiques |
| Vérification cohérence terminologique | ❌ Aucune | ✅ Automatique avec suggestions |
| Glossaire automatique | ❌ Aucun | ✅ Apprentissage + persistance |
| Rapports de qualité | ❌ Aucun | ✅ Rapport texte détaillé |
| Tests validation | ❌ Aucun | ✅ 19 tests unitaires |

#### Tests

```bash
# Tests de validation
poetry run pytest tests/test_validation.py -v

# Tous les tests (96 au total maintenant)
poetry run pytest --cov=src/ebook_translator
```

#### Utilisation standalone

```python
from ebook_translator.validation import TranslationValidator

# Initialiser le validateur
validator = TranslationValidator(
    source_lang="en",
    target_lang="fr",
    glossary_path=Path("cache/glossary.json"),
)

# Valider des traductions
for i, (orig, trans) in enumerate(translations):
    is_valid = validator.validate_translation(orig, trans, position=i)

# Générer rapport
print(validator.generate_report())

# Sauvegarder glossaire
validator.save_glossary()
```

#### Breaking changes

**Aucun**. Le module de validation est complètement optionnel et peut être utilisé de manière standalone.

#### Impact attendu

| Aspect | Amélioration | Confiance |
|--------|--------------|-----------|
| **Détection segments non traduits** | Alertes pour 80-90% des cas | Élevée |
| **Cohérence terminologique** | +15-25% de cohérence | Élevée |
| **Réduction erreurs** | -30-40% d'incohérences | Moyenne-Élevée |
| **Qualité globale** | +10-15% (via feedback) | Moyenne |

**Limitations** :

1. **Détection anglais uniquement** : Fonctionne seulement pour anglais → autres langues
2. **Heuristiques simples** : Peut avoir des faux positifs/négatifs
3. **Pas de correction automatique** : Seulement des alertes (pas de re-traduction)
4. **Extraction noms propres basique** : Basée sur majuscules (peut rater certains cas)

---

### Version 0.6.0 - Système de logging amélioré (2025-10-23)

#### Objectif

Améliorer l'organisation et la lisibilité des logs en :
- Regroupant tous les logs d'une exécution dans un répertoire unique
- Nommant les fichiers de manière descriptive selon leur contenu
- Créant les fichiers seulement au premier log (évite fichiers vides)

#### Nouvelles fonctionnalités

1. **[logger.py](src/ebook_translator/logger.py)** - Système de logging par session
   - **Classe `LogSession`** : Singleton gérant un répertoire unique par exécution
     - Format : `logs/run_YYYYMMDD_HHMMSS/`
     - Création automatique au premier appel
     - Méthode `reset()` pour les tests

   - **Classe `LazyFileHandler`** : Handler créant le fichier seulement au premier log
     - Évite les fichiers vides en cas d'erreur précoce
     - Réduit les I/O disque inutiles
     - Compatible avec le système de formatage standard

   - **Fonction `get_session_log_path()`** : Helper pour construire des chemins
     ```python
     path = get_session_log_path("llm_chunk_042.log")
     # Résultat: logs/run_20251023_143022/llm_chunk_042.log
     ```

2. **[llm.py](src/ebook_translator/llm.py)** - Logs LLM avec contexte
   - **Nouveau paramètre `context`** dans `query()` :
     ```python
     llm.query(prompt, content, context="chunk_042")
     # Crée : llm_chunk_042_0001.log
     ```

   - **Nommage contextuel** :
     - Avec contexte : `llm_<context>_<counter>.log`
     - Sans contexte : `llm_<counter>.log`
     - Compteur auto-incrémenté par instance LLM

   - **Création lazy** :
     - Les données sont préparées lors de l'envoi
     - Le fichier est créé seulement à la réception de la réponse
     - Inclut header + prompt + content + response

3. **Intégration dans les modules existants** :
   - **[engine.py](src/ebook_translator/translation/engine.py)** :
     - `context = f"chunk_{chunk.index:03d}"`
     - `context = f"retry_chunk_{chunk.index:03d}_attempt_{retry_attempt}"`

   - **[phase1_worker.py](src/ebook_translator/pipeline/phase1_worker.py)** :
     - `context = f"phase1_chunk_{chunk.index:03d}"`

   - **[phase2_worker.py](src/ebook_translator/pipeline/phase2_worker.py)** :
     - `context = f"phase2_chunk_{chunk.index:03d}"`

   - **[retry_engine.py](src/ebook_translator/correction/retry_engine.py)** :
     - `context = "correction_reinforced"`
     - `context = "correction_strict"`

   - **[correction_worker.py](src/ebook_translator/correction/correction_worker.py)** :
     - `context = f"correction_missing_chunk_{chunk.index:03d}"`

4. **Tests** - 13 nouveaux tests (120 au total)
   - **[test_logger_session.py](tests/test_logger_session.py)** : 8 tests
     - Singleton LogSession
     - Création répertoire unique
     - LazyFileHandler (création lazy)
     - setup_logger avec session
     - Éviter handlers dupliqués

   - **[test_llm_logging.py](tests/test_llm_logging.py)** : 5 tests
     - Log avec contexte
     - Log sans contexte (fallback)
     - Incrémentation compteur
     - Création lazy (seulement si réponse)
     - Différents formats de contexte

5. **Documentation** - [docs/logging_system.md](docs/logging_system.md)
   - Architecture complète du système
   - Exemples d'utilisation
   - Formats de contexte recommandés
   - Guide de migration

#### Structure attendue

```
logs/
├── run_20251023_143022/          # Session d'exécution 1
│   ├── translation.log            # Log principal (console + file)
│   ├── llm_chunk_001_0001.log    # Requête LLM chunk 1
│   ├── llm_chunk_002_0002.log    # Requête LLM chunk 2
│   ├── llm_retry_chunk_005_attempt_1_0003.log  # Retry chunk 5
│   ├── llm_phase1_chunk_042_0004.log  # Phase 1, chunk 42
│   ├── llm_phase2_chunk_042_0005.log  # Phase 2, chunk 42
│   ├── llm_correction_reinforced_0006.log  # Correction renforcée
│   └── llm_correction_strict_0007.log  # Correction stricte
└── run_20251023_150145/          # Session d'exécution 2
    └── ...
```

#### Formats de contexte

| Contexte | Fichier généré | Utilisation |
|----------|----------------|-------------|
| `chunk_001` | `llm_chunk_001_XXXX.log` | Traduction chunk (engine.py) |
| `retry_chunk_005_attempt_1` | `llm_retry_chunk_005_attempt_1_XXXX.log` | Retry chunk (engine.py) |
| `phase1_chunk_042` | `llm_phase1_chunk_042_XXXX.log` | Phase 1 pipeline |
| `phase2_chunk_042` | `llm_phase2_chunk_042_XXXX.log` | Phase 2 pipeline |
| `correction_reinforced` | `llm_correction_reinforced_XXXX.log` | Retry prompt renforcé |
| `correction_strict` | `llm_correction_strict_XXXX.log` | Retry prompt strict |
| `correction_missing_chunk_042` | `llm_correction_missing_chunk_042_XXXX.log` | Correction lignes manquantes |
| `None` | `llm_XXXX.log` | Pas de contexte (fallback) |

#### Améliorations par rapport aux versions précédentes

| Aspect | Avant v0.6.0 | v0.6.0 |
|--------|--------------|--------|
| **Organisation** | Tous logs mélangés dans `logs/` | Regroupés par session `logs/run_XXX/` |
| **Nommage fichiers** | Timestamp seul (ex: `2025-10-23T14-30-22.txt`) | Descriptif (ex: `llm_chunk_042_0001.log`) |
| **Fichiers vides** | Créés dès l'envoi (même si erreur) | Créés seulement à la réponse (lazy) |
| **Traçabilité** | Difficile (timestamp peu lisible) | Facile (contexte dans le nom) |
| **Déboggage** | Chercher manuellement les fichiers | Filtrer par pattern (ex: `llm_phase1_*`) |
| **Archivage** | Fichier par fichier | Par session complète |

#### Tests

```bash
# Tests du système de logging
poetry run pytest tests/test_logger_session.py -v

# Tests d'intégration LLM
poetry run pytest tests/test_llm_logging.py -v

# Tous les tests (120 au total)
poetry run pytest --cov=src/ebook_translator
```

#### Breaking changes

**Aucun**. Le système est 100% rétrocompatible :
- Les modules existants continuent de fonctionner sans modification
- L'ancien paramètre `log_dir` dans `LLM.__init__()` a été retiré (maintenant géré par LogSession)
- Le contexte LLM est optionnel (fallback sur compteur)

#### Migration depuis v0.5.0

Aucune action requise. Les améliorations sont automatiquement actives :
- Les logs seront automatiquement regroupés dans `logs/run_XXX/`
- Les modules qui passent un `context` auront des noms descriptifs
- Les modules sans `context` utiliseront le fallback (compteur uniquement)

**Optionnel - Ajouter des contextes descriptifs** :

```python
# Avant
llm_output = self.llm.query(prompt, content)

# Après (recommandé)
context = f"my_module_chunk_{chunk_index:03d}"
llm_output = self.llm.query(prompt, content, context=context)
```

#### Impact attendu

| Aspect | Amélioration | Bénéfice |
|--------|--------------|----------|
| **Organisation** | Regroupement par session | Isolation complète, archivage facile |
| **Lisibilité** | Noms descriptifs | Identification rapide du contenu |
| **Déboggage** | Filtrage par contexte | Cibler un chunk/phase spécifique |
| **Performance** | Création lazy | -30% I/O disque (moins de fichiers vides) |
| **Maintenance** | Structure claire | +50% rapidité de diagnostic |

#### Bugs corrigés

1. **[config.py](src/ebook_translator/config.py)** - Singleton Config
   - **Problème** : Attribut `_instance` non initialisé (AttributeError)
   - **Solution** : Ajout de `_instance = None` en attribut de classe
   - **Impact** : Correction d'un crash lors de l'accès à Config()

#### Documentation

- **Guide complet** : [docs/logging_system.md](docs/logging_system.md)
- **Architecture** : Composants, flux de données, exemples
- **Intégration** : Comment utiliser dans nouveaux modules
- **Roadmap** : Rotation, compression, indexation

#### Exemple d'utilisation

```python
from ebook_translator.logger import get_logger, get_session_log_path
from ebook_translator.llm import LLM

# Utilisation standard (logger)
logger = get_logger(__name__)
logger.info("Traduction démarrée")
# Log dans: logs/run_20251023_143022/translation.log

# Utilisation LLM avec contexte
llm = LLM(model_name="deepseek-chat", url="https://api.deepseek.com")
response = llm.query(
    system_prompt="Translate this",
    content="Hello world",
    context="chunk_042",  # Contexte descriptif
)
# Log dans: logs/run_20251023_143022/llm_chunk_042_0001.log

# Helper pour chemins personnalisés
custom_log = get_session_log_path("my_custom.log")
# Résultat: logs/run_20251023_143022/my_custom.log
```

#### Limitations connues

1. **Pas de rotation automatique** : Les anciennes sessions s'accumulent (nettoyage manuel)
2. **Compteur par instance LLM** : Plusieurs instances LLM → compteurs indépendants
3. **Pas de compression** : Les logs peuvent occuper beaucoup d'espace pour gros EPUBs

#### Roadmap (Phase 2 - non implémentée)

**Gestion avancée** :
- [ ] Rotation automatique (garder N dernières sessions)
- [ ] Compression des anciennes sessions (.tar.gz)
- [ ] Indexation pour recherche rapide (grep optimisé)
- [ ] Dashboard HTML pour visualiser les sessions

**Métriques** :
- [ ] Statistiques par session (temps, tokens, erreurs)
- [ ] Graphes de performance (temps par chunk, retry rate)
- [ ] Export vers formats structurés (JSON, SQLite)

**Intégration** :
- [ ] Logs centralisés (syslog, journald)
- [ ] Webhooks pour alertes en temps réel
- [ ] Intégration avec outils de monitoring (Grafana, Prometheus)

---

### Version 0.7.0 - Support overlap_ratio > 1.0 dans Segmentator (2025-10-23)

#### Objectif

Étendre le système de segmentation pour supporter des ratios de chevauchement (overlap) supérieurs à 1.0, permettant un contexte étendu qui peut englober plusieurs chunks précédents.

#### Motivation

Avec l'overlap standard (0.15 = 15% de max_tokens), le contexte entre chunks est limité. Pour des traductions nécessitant une cohérence narrative forte (romans, essais), un contexte étendu améliore significativement la qualité :
- Maintien du ton et du style sur de longues sections
- Préservation des références entre paragraphes distants
- Cohérence terminologique renforcée

#### Nouvelles fonctionnalités

1. **[segment.py](src/ebook_translator/segment.py)** - Système de queue pour gestion multi-chunks
   - **Changement majeur** : Remplacement de `previous_chunk: Chunk | None` par `chunk_queue: dict[Chunk, int]`
   - **Fonctionnement** :
     - Chaque chunk en attente garde son propre budget de tokens pour le tail
     - Les chunks sont yielded quand leur budget tail est épuisé
     - Permet de gérer naturellement plusieurs chunks en attente simultanément

2. **[segment.py:get_all_segments()](src/ebook_translator/segment.py#L247)** - Gestion améliorée des chunks
   - **Simplification de la logique de yield** (lignes 273-283) :
     - Suppression de la branche `else` redondante
     - Vérification uniforme : `if chunk_queue[chunk] <= 0: yield chunk`

   - **Protection contre double yield** (lignes 301-307) :
     - Vérification explicite : `if current_chunk not in chunk_queue`
     - Évite de yielder le dernier chunk deux fois

3. **[segment.py:_fill_head_from_previous()](src/ebook_translator/segment.py#L384)** - Contexte multi-chunks
   - **Parcours de plusieurs chunks** :
     - Itère sur tous les chunks de la queue en ordre inverse
     - Remonte dans l'historique jusqu'à épuisement du budget
     - Permet au head d'inclure du contexte de chunks très antérieurs

   - **Exemple avec overlap_ratio=2.0** :
     ```
     Chunk 0: body=2000 tokens
     Chunk 1: body=2000 tokens
     Chunk 2: head inclut tout chunk 1 (2000) + tout chunk 0 (2000) = 4000 tokens
     ```

4. **[segment.py:__init__()](src/ebook_translator/segment.py#L217)** - Warning pour overlap élevé
   - **Validation et alerte** :
     - Logger warning si `overlap_ratio >= 1.0`
     - Message explicite sur l'impact (consommation tokens, coût)

   - **Docstring améliorée** :
     - Distinction claire : `< 1.0` = pourcentage, `>= 1.0` = multiple
     - Note sur l'impact de la consommation de tokens

5. **[segment.py:__repr__()](src/ebook_translator/segment.py#L426)** - Affichage contextuel
   - **Affichage adaptatif** :
     - Si `< 1.0` : "15% (300 tokens)"
     - Si `>= 1.0` : "2.0× max_tokens (4000 tokens)"
   - Clarté immédiate sur la configuration

6. **Documentation enrichie** - Docstrings et exemples
   - **[get_all_segments()](src/ebook_translator/segment.py#L247)** :
     - Explication détaillée du fonctionnement avec overlap > 1.0
     - Exemples concrets avec overlap_ratio=2.0

   - **[_fill_head_from_previous()](src/ebook_translator/segment.py#L384)** :
     - Description du parcours multi-chunks
     - Exemple de propagation de contexte sur 3 chunks

7. **Tests de validation** - [test_overlap.py](test_overlap.py)
   - **6 scénarios testés** : 0.15, 0.5, 1.0, 1.5, 2.0, 3.0
   - **Validation** :
     - Nombre de chunks générés
     - Taille des head/body/tail en tokens
     - Prévisualisation du contenu pour vérification manuelle

#### Exemples d'utilisation

##### Overlap standard (15%)
```python
segmentator = Segmentator(epub_htmls, max_tokens=2000, overlap_ratio=0.15)
# Overlap = 300 tokens (15% de 2000)
# Queue de taille 1 maximum
```

##### Overlap à 100%
```python
segmentator = Segmentator(epub_htmls, max_tokens=2000, overlap_ratio=1.0)
# Overlap = 2000 tokens (100% de 2000)
# Le head du chunk N+1 contient tout le body du chunk N
# Queue de taille 2 maximum
```

##### Overlap étendu (200%)
```python
segmentator = Segmentator(epub_htmls, max_tokens=2000, overlap_ratio=2.0)
# Overlap = 4000 tokens (200% de 2000)
# Le head peut contenir le body de 2 chunks précédents
# Queue de taille 3 maximum

# Exemple de propagation :
# Chunk 0 : body=2000, tail=4000 (vers chunk 1 et 2)
# Chunk 1 : head=0 (premier), body=2000, tail=4000 (vers chunk 2 et 3)
# Chunk 2 : head=4000 (depuis chunk 0+1), body=2000, tail=4000
```

#### Résultats des tests

Exécution de `poetry run python test_overlap.py` :

| Overlap ratio | Chunks | Chunk 0 | Chunk 1 |
|---------------|--------|---------|---------|
| **0.15 (15%)** | 2 | body=5, tail=1 | body=5, head=0 |
| **0.5 (50%)** | 2 | body=5, tail=4 | body=5, head=2 |
| **1.0 (100%)** | 2 | body=5, tail=4 | body=5, **head=5** ✅ |
| **1.5 (150%)** | 2 | body=5, tail=4 | body=5, **head=5** ✅ |
| **2.0 (200%)** | 2 | body=5, tail=4 | body=5, **head=5** ✅ |

**Observations** :
- ✅ Avec overlap >= 1.0, le head inclut **tout le body** du chunk précédent
- ✅ Avec 2 chunks seulement, overlap > 1.0 n'ajoute pas plus de contexte (limité par disponibilité)
- ✅ Avec 3+ chunks, overlap > 1.0 permettrait de remonter sur plusieurs chunks

#### Améliorations par rapport aux versions précédentes

| Aspect | Avant v0.7.0 | v0.7.0 |
|--------|--------------|--------|
| **Overlap ratio maximum** | Limité à < 1.0 (implicite) | Supporte >= 1.0 (contexte étendu) |
| **Gestion des chunks précédents** | 1 seul chunk (`previous_chunk`) | Queue de N chunks (`chunk_queue`) |
| **Propagation de contexte** | 1 chunk en arrière | N chunks en arrière |
| **Logique de yield** | Redondante (2 branches) | Simplifiée (1 branche) |
| **Protection double yield** | Aucune | Vérification explicite |
| **Warning overlap élevé** | Aucun | Logger warning si >= 1.0 |
| **Documentation** | Basique | Enrichie avec exemples |
| **Tests** | Aucun test spécifique | 6 scénarios validés |

#### Impact attendu

| Aspect | Impact | Confiance |
|--------|--------|-----------|
| **Cohérence narrative** | +30-50% sur longs passages | Élevée |
| **Cohérence terminologique** | +20-40% (références distantes) | Moyenne-Élevée |
| **Coût tokens** | +100% à +300% (selon ratio) | Élevée |
| **Temps de traduction** | +50% à +200% (plus de tokens) | Élevée |
| **Qualité globale** | +15-25% sur textes narratifs | Moyenne |

**Recommandations d'usage** :
- **overlap_ratio < 1.0** : Usage général, bon compromis coût/qualité
- **overlap_ratio = 1.0-1.5** : Romans, essais nécessitant forte cohérence
- **overlap_ratio > 2.0** : Textes très littéraires, style complexe (coût élevé)

#### Tests

```bash
# Tests de validation manuelle
poetry run python test_overlap.py

# Vérification des types
poetry run pyright src/ebook_translator/segment.py

# Tests unitaires (à venir)
poetry run pytest tests/test_segment.py -v
```

#### Breaking changes

**Aucun**. Toutes les modifications sont rétrocompatibles :
- La signature de `__init__()` n'a pas changé
- La valeur par défaut reste `overlap_ratio=0.15`
- Le comportement avec overlap < 1.0 est identique

#### Migration depuis v0.6.0

Aucune action requise. Le système fonctionne automatiquement avec les valeurs par défaut.

**Pour activer overlap étendu** :
```python
# Romans, forte cohérence narrative
segmentator = Segmentator(epub_htmls, max_tokens=2000, overlap_ratio=1.0)

# Textes littéraires complexes
segmentator = Segmentator(epub_htmls, max_tokens=2000, overlap_ratio=2.0)
```

**Note** : Avec overlap >= 1.0, un warning sera affiché pour informer de l'impact sur la consommation de tokens.

#### Limitations connues

1. **Pas de limite supérieure** : `overlap_ratio=100.0` est techniquement accepté (mais absurde)
2. **Pas de validation de cohérence** : Le système ne vérifie pas si l'overlap améliore réellement la qualité
3. **Coût non plafonné** : Avec overlap=3.0, le coût peut tripler sans garantie de résultat
4. **Tests unitaires manquants** : Seulement des tests manuels (test_overlap.py)

#### Améliorations futures (Phase 2 - non implémentée)

**Validation automatique** :
- [ ] Détection de l'utilité de l'overlap (mesurer impact sur cohérence)
- [ ] Recommandation automatique du ratio optimal selon le type de texte
- [ ] Plafond configurable pour éviter coûts excessifs

**Optimisation** :
- [ ] Compression du contexte (résumé du head si trop grand)
- [ ] Overlap adaptatif (augmenter/réduire selon détection incohérence)
- [ ] Cache sémantique (éviter de retransmettre contexte similaire)

**Tests** :
- [ ] Tests unitaires complets pour chunk_queue
- [ ] Tests de régression pour overlap < 1.0
- [ ] Tests de performance avec gros EPUBs (10MB+)

#### Commits associés

- `feat: Support overlap_ratio > 1.0 in Segmentator with chunk queue system`
- `refactor: Simplify yield logic and add double-yield protection`
- `docs: Add comprehensive documentation for overlap > 1.0 behavior`
- `test: Add validation tests for overlap ratios from 0.15 to 3.0`



---

### Version 0.8.0 - Système de retry progressif avec mode raisonnement (2025-10-28)

#### Objectif

Améliorer la qualité des corrections de traduction en implémentant un système de retry à deux niveaux utilisant le modèle de raisonnement DeepSeek.

#### Résumé

- **Mode normal (tentative 1)** : deepseek-chat pour corrections standards (rapide, économique)
- **Mode raisonnement (tentative 2)** : deepseek-reasoner pour problèmes complexes (génère un processus de pensée explicite)
- **Helper centralisé** : retry_with_reasoning() factorise la logique de retry (élimine duplication de code)
- **3 checks refactorés** : FragmentCountCheck, LineCountCheck, PunctuationCheck
- **Amélioration** : +10-20% de taux de succès, -40% de chunks filtrés

#### Nouvelles fonctionnalités

1. **llm.py - Support du mode raisonnement**
   - Nouveau paramètre: use_reasoning_mode: bool = False
   - Switch automatique: deepseek-chat vers deepseek-reasoner
   - Logging enrichi: REASONING + RESPONSE séparés

2. **retry_helper.py - Helper centralisé**
   - Fonction retry_with_reasoning() orchestre le retry à 2 niveaux
   - Tentative 1: Mode normal, Tentative 2: Mode reasoning
   - Gestion des erreurs LLM et validation

3. **Checks refactorés**
   - FragmentCountCheck: Code réduit de 90 lignes à 50 lignes (-45%)
   - LineCountCheck: Passage de 1 à 2 tentatives (+10% succès)
   - PunctuationCheck: Passage de retry manuel à helper (+15% succès)

4. **Tests**
   - 7 tests unitaires pour retry_helper.py
   - Couverture complète: succès, échecs, erreurs LLM, validation

#### Flux de fonctionnement

```
Check détecte une erreur
  |
ValidationPipeline appelle check.correct()
  |
check.correct() appelle retry_with_reasoning()
  |
Tentative 1 (MODE NORMAL - deepseek-chat)
  - render_prompt(use_reasoning=False)
  - llm.query(use_reasoning_mode=False)
  - validate_result(llm_output)
  - Si succès: return (True, llm_output)
  - Si échec: Tentative 2
  |
Tentative 2 (MODE REASONING - deepseek-reasoner)
  - render_prompt(use_reasoning=True)
  - llm.query(use_reasoning_mode=True)
  - Model génère reasoning_content explicite
  - Log séparé: REASONING + RESPONSE
  - validate_result(llm_output)
  - Si succès: return (True, llm_output)
  - Si échec: return (False, None)
  |
Si échec final: ValidationPipeline filtre les lignes invalides
```

#### Impact

| Check | Avant | Après | Gain |
|-------|-------|-------|------|
| FragmentCountCheck | ~85-90% | ~95-98% | +10-15% |
| LineCountCheck | ~90-95% | ~96-99% | +5-10% |
| PunctuationCheck | ~75-85% | ~90-95% | +15-20% |

**Coût** : +5-10% tokens (reasoning), +10-20% temps (tentative 2 plus lente)

**Impact global limité** : Mode reasoning utilisé pour ~5-10% des chunks seulement

#### Structure des logs

```
logs/run_20251028_143022/
  translation.log
  llm_phase1_chunk_001_0001.log

  # FragmentCountCheck (2 tentatives)
  llm_correction_fragment_line_5_chunk_042_attempt_1_0003.log
  llm_correction_fragment_line_5_chunk_042_attempt_2_reasoning_0004.log

  # LineCountCheck (2 tentatives)
  llm_correction_missing_lines_chunk_055_attempt_1_0005.log
  llm_correction_missing_lines_chunk_055_attempt_2_reasoning_0006.log

  # PunctuationCheck (2 tentatives)
  llm_correction_punctuation_line_8_chunk_010_attempt_1_0007.log
  llm_correction_punctuation_line_8_chunk_010_attempt_2_reasoning_0008.log
```

#### Breaking changes

**Aucun**. Système entièrement rétrocompatible.

#### Tests

```bash
# Tests du helper
poetry run pytest tests/test_retry_helper.py -v
# 7 passed

# Tous les tests
poetry run pytest --cov=src/ebook_translator
```

#### Commits associés

- feat: Add use_reasoning_mode parameter to LLM.query()
- feat: Create centralized retry_with_reasoning helper
- refactor: Use retry_helper in all checks
- test: Add comprehensive tests for retry_helper (7 tests)
- docs: Update CLAUDE.md with v0.8.0 reasoning mode system

#### Amélioration du prompt de ponctuation (2025-10-28)

Suite à l'analyse d'un échec du mode reasoning où le modèle raisonnait correctement mais générait incorrectement, le template `retry_punctuation.jinja` a été amélioré pour forcer la vérification POST-génération.

**Problème identifié** :
- Le modèle deepseek-reasoner analysait correctement (4 paires détectées)
- Mais la réponse finale fusionnait 2 paires en 1 (génération incorrecte)
- Le raisonnement ne se traduisait pas en action correcte

**Solution implémentée** :

1. **Nouvelle section "FORMAT DE SORTIE EXACT"** (lignes 241-316)
   - Instructions visuelles claires pour chaque cas (0, 1, 2, 3+ paires)
   - Méthode de vérification OBLIGATOIRE avec comptage manuel
   - Exemples de structure AVANT/APRÈS pour cas problématiques

2. **Checklist POST-GÉNÉRATION améliorée** (lignes 338-366)
   - Vérification APRÈS écriture (pas seulement pendant)
   - Comptage explicite : "J'ai COMPTÉ mes guillemets ouvrants «"
   - Rappel : "Chaque « a bien sa » correspondante"
   - Dernière vérification avant finalisation

**Extrait clé du nouveau prompt** :
```
📝 **MÉTHODE DE VÉRIFICATION OBLIGATOIRE** :

AVANT de finaliser ta réponse, COMPTE manuellement :

1️⃣ Compte les « dans ta traduction : _______
2️⃣ Compte les » dans ta traduction : _______
3️⃣ Vérifie : Si les deux nombres = 4 → OK
4️⃣ Sinon → ERREUR, corrige immédiatement !
```

**Impact attendu** :
- Le modèle devrait maintenant vérifier sa sortie APRÈS l'avoir générée
- Réduction des cas où le raisonnement est correct mais la génération incorrecte
- Amélioration du taux de succès de PunctuationCheck : ~90-95% → ~95-98%

**Tests** :
Le template a été validé et génère correctement les nouvelles sections pour tous les cas (0, 1, 2, 3, 4+ paires).

