# Configuration et installation

## Prérequis

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) (gestionnaire de dépendances)

## Installation

```bash
# Installer les dépendances
uv sync --group dev

# Configurer les variables d'environnement
cp .env.example .env
# Éditer .env et ajouter votre clé API
```

## Variables d'environnement

| Variable | Obligatoire | Défaut | Description |
|----------|-------------|--------|-------------|
| `DEEPSEEK_API_KEY` | Oui | — | Clé API DeepSeek |
| `DEEPSEEK_URL` | Non | `https://api.deepseek.com` | URL de base de l'API |
| `OPENAI_API_KEY` | Non | — | Alternative à DeepSeek |

## Pre-commit hooks

```bash
uv run pre-commit install
```

Les hooks exécutent automatiquement : ruff format, ruff check, basedpyright.

## Vérification de l'installation

```bash
uv run pytest                    # Tests unitaires
uv run basedpyright src/         # Typage (doit retourner 0 errors)
uv run pre-commit run --all-files
```

## Dépannage

**Clé API invalide** : vérifier que `DEEPSEEK_API_KEY` est bien définie dans `.env` (pas dans l'environnement shell).

**Erreurs de types** : s'assurer que `uv sync --group dev` a bien installé basedpyright.

**Tests qui échouent** : le test EPUB de référence se trouve dans `tests/` (Le Petit Prince). Vérifier que le fichier est présent.
