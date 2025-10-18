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
- `worker.py` crée actuellement des futures factices qui n'appellent pas réellement le traducteur
- Les templates de prompts Jinja2 sont référencés mais ne sont pas présents dans le dépôt
- Aucune couverture de tests dans le répertoire `tests/`
