# Traducteur d'Ebooks

> Traduisez des fichiers EPUB en utilisant des Large Language Models (DeepSeek, OpenAI et autres APIs compatibles OpenAI)

[🇬🇧 English version](README.md)

## Vue d'ensemble

**Ebook Translator** est un outil Python qui traduit des fichiers EPUB en utilisant des Large Language Models (LLM) tels que DeepSeek, OpenAI et d'autres APIs compatibles OpenAI. L'outil segmente intelligemment le contenu des ebooks, le traduit à l'aide d'appels LLM asynchrones, et reconstruit l'EPUB traduit tout en préservant la structure et les métadonnées.

## Fonctionnalités

- **Traduction EPUB**: Traduit des fichiers EPUB entiers en maintenant la structure
- **Propulsé par LLM**: Utilise des modèles de langage avancés (DeepSeek, OpenAI, etc.)
- **Segmentation intelligente**: Découpe intelligemment le contenu avec limites de tokens et chevauchement
- **Traitement asynchrone**: Parallélise les appels de traduction pour de meilleures performances
- **Préservation des métadonnées**: Conserve le titre, les auteurs et la structure d'origine
- **Structure HTML**: Préserve le formatage, les images, le CSS et la mise en page

## Prérequis

- Python 3.12 ou supérieur
- Poetry (pour la gestion des dépendances)
- Clé API pour DeepSeek ou OpenAI

## Installation

1. **Cloner le dépôt**:
   ```bash
   git clone https://github.com/NeOzay/ebook-translator.git
   cd ebook-translator
   ```

2. **Installer les dépendances**:
   ```bash
   poetry install
   ```

3. **Configurer les clés API**:
   ```bash
   cp .env.example .env
   ```

   Éditez `.env` et ajoutez votre clé API:
   ```bash
   API_KEY=sk-votre-cle-api-ici
   ```

### Obtenir des clés API

**DeepSeek** (Recommandé):
- Créez un compte sur [DeepSeek Platform](https://platform.deepseek.com)
- Accédez à [API Keys](https://platform.deepseek.com/api_keys)
- Générez une nouvelle clé API

**OpenAI** (Alternative):
- Créez un compte sur [OpenAI Platform](https://platform.openai.com)
- Accédez à [API Keys](https://platform.openai.com/api-keys)
- Générez une nouvelle clé API

## Utilisation

```bash
python -m ebook_translator
```

Ou directement:
```bash
python src/ebook_translator/__main__.py
```

## Configuration

### Variables d'environnement

| Variable | Obligatoire | Défaut | Description |
|----------|-------------|--------|-------------|
| `API_KEY` | ✅ Oui | - | Clé API DeepSeek pour l'authentification |
| `DEEPSEEK_URL` | ❌ Non | `https://api.deepseek.com` | URL de base de l'API DeepSeek |
| `OPENAI_API_KEY` | ❌ Non | - | Clé API OpenAI (alternative) |

## Développement

**Vérification des types**:
```bash
pyright src/ebook_translator
```

**Exécuter les tests**:
```bash
pytest tests/
```

## Architecture

Le pipeline de traduction suit ce flux:

1. **Chargement EPUB** - Lit l'EPUB, extrait les métadonnées et l'ordre du spine
2. **Segmentation** - Découpe le contenu en segments limités en tokens avec chevauchement
3. **Traduction** - Parallélise les appels de traduction LLM
4. **Reconstruction** - Remplace le texte original par les traductions dans le DOM
5. **Génération EPUB** - Écrit un nouvel EPUB avec le contenu traduit

### Composants clés

- **Segmentator** ([segment.py](src/ebook_translator/segment.py)) - Découpe le contenu avec limites de tokens et chevauchement
- **HtmlPage** ([htmlpage.py](src/ebook_translator/htmlpage.py)) - Parse et reconstruit le HTML avec les traductions
- **AsyncLLMTranslator** ([llm.py](src/ebook_translator/llm.py)) - Wrapper async pour les appels API LLM
- **TranslationWorkerFuture** ([worker.py](src/ebook_translator/worker.py)) - Parallélise les tâches de traduction

## Sécurité

**IMPORTANT**:
- ⚠️ Ne commitez **JAMAIS** le fichier `.env` dans git (déjà dans `.gitignore`)
- ⚠️ Ne partagez **JAMAIS** vos clés API publiquement
- ⚠️ Si une clé est compromise, **révoquez-la immédiatement** sur la plateforme

## Licence

Ce projet est sous licence MIT.

## Auteur

**NeOzay** - [neozay.ozay@gmail.com](mailto:neozay.ozay@gmail.com)

## Liens

- [Page d'accueil](https://github.com/NeOzay/ebook-translator)
- [Issues](https://github.com/NeOzay/ebook-translator/issues)

## Contribution

Les contributions sont les bienvenues ! N'hésitez pas à soumettre une Pull Request.
