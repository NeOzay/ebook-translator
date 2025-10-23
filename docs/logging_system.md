# Système de Logging

## Vue d'ensemble

Le système de logging de l'ebook-translator a été conçu pour :
- **Regrouper** tous les logs d'une exécution dans un répertoire unique
- **Nommer** les fichiers de manière descriptive selon leur contenu
- **Créer** les fichiers seulement au premier log (évite fichiers vides)

## Architecture

### Structure des répertoires

```
logs/
├── run_20251023_143022/          # Session d'exécution 1
│   ├── translation.log            # Log principal (console + file)
│   ├── llm_chunk_001_0001.log    # Requête LLM pour chunk 1
│   ├── llm_chunk_002_0002.log    # Requête LLM pour chunk 2
│   ├── llm_retry_chunk_005_attempt_1_0003.log  # Retry chunk 5
│   ├── llm_phase1_chunk_042_0004.log  # Phase 1, chunk 42
│   └── llm_phase2_chunk_042_0005.log  # Phase 2, chunk 42
└── run_20251023_150145/          # Session d'exécution 2
    └── ...
```

### Composants principaux

#### 1. LogSession (Singleton)

Gère le répertoire de session unique pour toute l'exécution.

```python
from ebook_translator.logger import LogSession

# Obtenir le répertoire de session
session_dir = LogSession.get_session_dir()
# Exemple: logs/run_20251023_143022/

# Reset (utile pour les tests)
LogSession.reset()
```

**Caractéristiques** :
- Singleton : une seule instance par processus
- Création automatique du répertoire au premier appel
- Format : `logs/run_YYYYMMDD_HHMMSS/`

#### 2. LazyFileHandler

Handler de logging qui crée le fichier seulement au premier message.

```python
from pathlib import Path
from ebook_translator.logger import LazyFileHandler

handler = LazyFileHandler(
    filename=Path("logs/my_log.log"),
    mode="a",
    encoding="utf-8",
)
# Le fichier n'existe pas encore !

logger.addHandler(handler)
logger.info("Premier message")
# Le fichier est créé maintenant
```

**Avantages** :
- Évite les fichiers vides en cas d'erreur précoce
- Économise les I/O disque
- Réduit le bruit dans le répertoire de logs

#### 3. setup_logger() et get_logger()

Fonctions de configuration centralisée.

```python
from ebook_translator.logger import setup_logger, get_logger

# Configuration explicite
logger = setup_logger(
    name=__name__,
    log_filename="my_module.log",  # Nom personnalisé
    level=logging.INFO,
    console_level=logging.ERROR,
    file_level=logging.DEBUG,
)

# Ou récupération simple
logger = get_logger(__name__)
```

**Fonctionnalités** :
- 2 handlers : console (compatible tqdm) + fichier (lazy)
- Évite les handlers dupliqués
- Utilise automatiquement le répertoire de session

#### 4. get_session_log_path()

Helper pour construire des chemins de logs.

```python
from ebook_translator.logger import get_session_log_path

# Chemin complet dans le répertoire de session
path = get_session_log_path("llm_chunk_042.log")
# Résultat: logs/run_20251023_143022/llm_chunk_042.log
```

## Utilisation

### Dans les modules standards

Utiliser le logger comme d'habitude :

```python
from ebook_translator.logger import get_logger

logger = get_logger(__name__)

logger.info("Traduction démarrée")
logger.error("Erreur lors de la traduction", exc_info=True)
```

Les logs apparaîtront :
- Sur la console (niveau ERROR uniquement)
- Dans `logs/run_XXX/translation.log` (tous niveaux)

### Dans le module LLM

Le LLM crée des logs individuels pour chaque requête avec contexte :

```python
from ebook_translator.llm import LLM

llm = LLM(...)

# Avec contexte descriptif
response = llm.query(
    system_prompt="Translate this",
    content="Hello world",
    context="chunk_042",  # Contexte optionnel
)
# Crée : logs/run_XXX/llm_chunk_042_0001.log
```

**Formats de contexte recommandés** :

| Contexte | Description | Fichier généré |
|----------|-------------|----------------|
| `chunk_001` | Traduction chunk 1 | `llm_chunk_001_0001.log` |
| `retry_chunk_005_attempt_1` | Retry chunk 5 | `llm_retry_chunk_005_attempt_1_0002.log` |
| `phase1_chunk_042` | Phase 1, chunk 42 | `llm_phase1_chunk_042_0003.log` |
| `phase2_chunk_042` | Phase 2, chunk 42 | `llm_phase2_chunk_042_0004.log` |
| `correction_reinforced` | Correction renforcée | `llm_correction_reinforced_0005.log` |
| `correction_strict` | Correction stricte | `llm_correction_strict_0006.log` |
| `None` | Pas de contexte | `llm_0007.log` |

**Note** : Le compteur (ex: `_0001`) est incrémenté à chaque requête LLM pour garantir l'unicité.

### Exemples d'intégration

#### engine.py (Translation Engine)

```python
def _request_translation(self, chunk: Chunk, ...):
    # ...
    context = f"chunk_{chunk.index:03d}"
    llm_output = self.llm.query(prompt, source_content, context=context)
    # Crée : llm_chunk_001_XXXX.log
```

#### phase1_worker.py (Pipeline Phase 1)

```python
def process_chunk(self, chunk: Chunk) -> bool:
    # ...
    context = f"phase1_chunk_{chunk.index:03d}"
    llm_output = self.llm.query(prompt, source_content, context=context)
    # Crée : llm_phase1_chunk_042_XXXX.log
```

#### retry_engine.py (Retry automatique)

```python
def _retry_with_reinforced_prompt(self, ...):
    # ...
    context = "correction_reinforced"
    response = self.llm.query(prompt, content, context=context)
    # Crée : llm_correction_reinforced_XXXX.log
```

## Format des logs LLM

Chaque fichier de log LLM contient :

```
=== LLM REQUEST LOG ===
Timestamp : 2025-10-23T14:30:22-00-00
Model     : deepseek-chat
Context   : chunk_042
Prompt len: 1234 chars
----------------------------------------

--- PROMPT ---
[Prompt système complet...]

--- CONTENT ---
<0/>Hello world
<1/>How are you?

--- RESPONSE ---
<0/>Bonjour le monde
<1/>Comment allez-vous ?
```

## Avantages du système

### 1. Organisation claire
- **Avant** : Tous les logs mélangés dans `logs/`
  ```
  logs/
  ├── translation_20251023_143022.log
  ├── 2025-10-23T14-30-22.txt
  ├── 2025-10-23T14-30-25.txt
  └── 2025-10-23T14-30-28.txt  # 😕 Quel chunk ?
  ```

- **Après** : Regroupés par session
  ```
  logs/
  └── run_20251023_143022/
      ├── translation.log
      ├── llm_chunk_001_0001.log  # ✅ Clair !
      └── llm_chunk_002_0002.log
  ```

### 2. Nommage descriptif
- Identifier rapidement le contenu d'un log
- Trier/filtrer facilement (ex: `llm_phase1_*`)
- Déboguer un chunk spécifique

### 3. Pas de fichiers vides
- Création lazy évite les fichiers inutiles
- Répertoire de logs plus propre
- Moins d'I/O disque

### 4. Isolation des sessions
- Plusieurs exécutions sans collision
- Historique complet par session
- Facile à archiver/supprimer

## Tests

Le système est couvert par 13 tests unitaires :

```bash
# Tests du système de logging
poetry run pytest tests/test_logger_session.py -v

# Tests d'intégration LLM
poetry run pytest tests/test_llm_logging.py -v

# Tous les tests
poetry run pytest --cov=src/ebook_translator
```

## Migration

Le système est **100% rétrocompatible** :

- Les modules existants continuent de fonctionner sans modification
- L'ancien paramètre `log_dir` est toujours supporté
- Le contexte LLM est optionnel (fallback sur compteur)

**Aucune migration requise** pour les utilisateurs existants.

## Roadmap

Améliorations futures possibles :

- [ ] Rotation automatique (garder seulement N dernières sessions)
- [ ] Compression des anciennes sessions (.tar.gz)
- [ ] Indexation des logs pour recherche rapide
- [ ] Dashboard HTML pour visualiser les sessions
- [ ] Export des logs vers formats structurés (JSON, SQLite)

## Voir aussi

- [CLAUDE.md](../CLAUDE.md) - Instructions projet
- [error_handling.md](error_handling.md) - Gestion des erreurs
- [src/ebook_translator/logger.py](../src/ebook_translator/logger.py) - Code source
