# Configuration et installation

> Guide complet pour configurer l'environnement de développement du traducteur d'ebooks.

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

## Installation des dépendances

### Prérequis

- Python 3.10+
- Poetry (gestionnaire de dépendances)

### Installation

Le projet utilise Poetry pour la gestion des dépendances :

```bash
# Installer les dépendances de production
poetry install

# Installer avec les dépendances de développement
poetry install --with dev
```

### Dépendances de développement

Les dépendances optionnelles `[dev]` incluent :
- `pytest` : Framework de tests
- `pytest-cov` : Couverture de code
- `pyright` : Vérification des types

Pour installer manuellement :
```bash
pip install -e ".[dev]"
```

## Commandes de développement

### Exécution du traducteur

```bash
# Via module Python
python -m ebook_translator

# Ou directement
python src/ebook_translator/__main__.py
```

Le point d'entrée principal est [src/ebook_translator/__main__.py](../src/ebook_translator/__main__.py).

### Tests

```bash
# Exécuter tous les tests
poetry run pytest

# Tests avec couverture
poetry run pytest --cov=src/ebook_translator --cov-report=html

# Tests spécifiques
poetry run pytest tests/test_segment.py -v
```

### Vérification des types

Pyright est configuré avec l'environnement d'exécution dans `pyrightconfig.json` :

```bash
# Vérifier tous les fichiers
poetry run pyright src/ebook_translator

# Vérifier un fichier spécifique
poetry run pyright src/ebook_translator/segment.py
```

### Linting et formatage

```bash
# Vérifier le style de code
poetry run ruff check src/

# Formater le code
poetry run black src/
```

## Configuration

### Sélection du modèle LLM

Passer `model_name` à `translator()` :

```python
from ebook_translator.llm import LLM

# DeepSeek (par défaut)
llm = LLM(model_name="deepseek-chat")

# OpenAI
llm = LLM(model_name="gpt-4-turbo")

# Mode reasoning (DeepSeek)
llm = LLM(model_name="deepseek-chat")
response = llm.query(prompt, content, use_reasoning_mode=True)
```

### Paramètres de traduction

```python
from ebook_translator import EpubTranslator, Language

translator = EpubTranslator(llm, epub_path="book.epub")
translator.translate(
    target_language=Language.FRENCH,
    output_epub="book_fr.epub",
    max_concurrent=2,        # Nombre de traductions parallèles
    overlap_ratio=0.15,      # Chevauchement de contexte (15%)
)
```

### Configuration avancée

**Overlap ratio** :
- `< 1.0` : Pourcentage de max_tokens (ex: 0.15 = 15%)
- `>= 1.0` : Multiple de max_tokens (ex: 2.0 = 200%)
- Valeur recommandée : `0.15` (compromis coût/qualité)

**Max concurrent** :
- Réduit à `1-2` si rate limit fréquent
- Augmenté à `4-8` pour traductions rapides

**Température LLM** :
- Par défaut : `0.5` (cohérence optimale)
- Plus créatif : `0.7-0.85` (au détriment de la cohérence)

## Structure du projet

```
ebook-translator/
├── src/ebook_translator/     # Code source principal
│   ├── checks/              # Validation structurelle
│   ├── correction/          # Système de retry
│   ├── htmlpage/            # Manipulation HTML/DOM
│   ├── llm/                 # Client LLM et templates
│   ├── pipeline/            # Pipeline de traduction
│   ├── quality/             # Validation sémantique (optionnel)
│   ├── segmentation/        # Segmentation du contenu
│   ├── transition/          # Gestion des transitions
│   └── validation/          # Architecture de validation
├── template/                # Templates Jinja2 pour prompts
│   ├── common_translate_rules.jinja
│   ├── common_correct_rules.jinja
│   └── [7 templates spécifiques]
├── tests/                   # Tests unitaires
├── docs/                    # Documentation
├── logs/                    # Logs de traduction (par session)
└── cache/                   # Cache et glossaires

```

## Dépannage

### Problèmes courants

**1. Erreur "API key not found"**
```bash
# Vérifier que .env existe et contient la clé
cat .env

# Vérifier que python-dotenv charge correctement
python -c "from dotenv import load_dotenv; load_dotenv(); import os; print(os.getenv('DEEPSEEK_API_KEY'))"
```

**2. Erreur "Rate limit exceeded"**
- Réduire `max_concurrent` à 1-2
- Augmenter le délai entre requêtes (paramètre `retry_delay`)

**3. Tests échouent avec "Permission denied" (Windows)**
- Le système de Store utilise des verrous par fichier
- Assurez-vous qu'aucun autre processus n'accède aux fichiers de cache

**4. Pyright signale des erreurs de type**
- Vérifier que `pyrightconfig.json` pointe vers le bon environnement Python
- Exécuter `poetry install` pour régénérer les stubs de types

## Ressources

- **Documentation complète** : [CLAUDE.md](../CLAUDE.md)
- **Architecture technique** : [ARCHITECTURE.md](ARCHITECTURE.md)
- **Historique des versions** : [CHANGELOG.md](CHANGELOG.md)
- **Système de validation** : [VALIDATION.md](VALIDATION.md)
- **Architecture des templates** : [TEMPLATES.md](TEMPLATES.md)
- **Roadmap** : [ROADMAP.md](ROADMAP.md)
