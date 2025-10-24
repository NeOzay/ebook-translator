"""
Module de traduction d'ebooks via LLM.

Ebook Translator est un outil qui traduit des fichiers EPUB en utilisant
des Large Language Models (LLM) compatibles OpenAI comme DeepSeek.

Le processus de traduction :
1. Charge et parse l'EPUB source
2. Segmente le contenu en chunks limités en tokens avec chevauchement
3. Traduit chaque chunk via l'API LLM (avec cache sur disque)
4. Reconstruit l'EPUB traduit avec les métadonnées originales

Fonctionnalités principales :
- Support des formats bilingues (original + traduction)
- Cache persistant des traductions (évite les retraductions)
- Traitement parallèle des chunks
- Préservation de la structure HTML et des métadonnées EPUB
- Logs détaillés de chaque requête LLM

Organisation du package :
- llm.py : Client LLM avec templates Jinja2 et logging
- segment.py : Segmentation du contenu en chunks avec overlap
- store.py : Cache persistant des traductions (JSON)
- worker.py : Traitement parallèle des chunks
- htmlpage/ : Parsing et manipulation des pages HTML
- translation/ : Orchestration complète de la traduction

Exports publics :
    Classes principales :
        - LLM : Client pour les API LLM (DeepSeek, OpenAI, etc.)
        - Store : Cache persistant des traductions
        - Segmentator : Segmentation du contenu en chunks

    Classes HTML :
        - HtmlPage : Manipulation des pages HTML
        - BilingualFormat : Formats d'affichage bilingue
        - TagKey : Wrapper pour utiliser Tags comme clés

    Dataclasses :
        - Chunk : Représente un morceau de contenu à traduire
        - Language : Énumération des langues supportées

    Constantes :
        - FRAGMENT_SEPARATOR : Séparateur de fragments HTML
        - VALID_ROOT_TAGS : Balises HTML valides pour traduction
        - DEFAULT_OVERLAP_RATIO : Ratio de chevauchement entre chunks
        - DEFAULT_ENCODING : Encodage tiktoken par défaut

Usage minimal :
    >>> from ebook_translator import LLM, EpubTranslator
    >>> from ebook_translator.translation import Language
    >>>
    >>> # Configurer le LLM (requiert DEEPSEEK_API_KEY dans .env)
    >>> llm = LLM(
    ...     model_name="deepseek-chat",
    ...     url="https://api.deepseek.com",
    ...     max_tokens=1300
    ... )
    >>>
    >>> # Traduire un EPUB
    >>> translator = EpubTranslator(llm, epub_path="book.epub")
    >>> translator.translate(
    ...     target_language=Language.FRENCH,
    ...     output_epub="book_fr.epub",
    ...     max_concurrent=1
    ... )

Usage avancé avec cache et format bilingue :
    >>> from ebook_translator import (
    ...     LLM, EpubTranslator, Store, BilingualFormat
    ... )
    >>> from ebook_translator.translation import Language
    >>>
    >>> llm = LLM(model_name="deepseek-chat", max_tokens=1300)
    >>> store = Store(cache_dir=".translation_cache")
    >>> translator = EpubTranslator(llm, epub_path="book.epub")
    >>>
    >>> # Traduction avec format bilingue et cache
    >>> translator.translate(
    ...     target_language=Language.FRENCH,
    ...     output_epub="book_bilingual.epub",
    ...     max_concurrent=3,  # Traduction parallèle
    ...     bilingual_format=BilingualFormat.INLINE
    ... )

Configuration :
    Le module nécessite une clé API LLM. Créez un fichier .env :

        DEEPSEEK_API_KEY=sk-votre-cle-ici
        DEEPSEEK_URL=https://api.deepseek.com

    Voir .env.example et CLAUDE.md pour plus de détails.

Version: 0.1.0
Author: NeOzay
License: à définir
"""

# Classes LLM et traduction
from .llm import LLM
from .translation.language import Language

# Classes de segmentation et cache
from .segment import Chunk, Segmentator, DEFAULT_OVERLAP_RATIO, DEFAULT_ENCODING
from .store import Store

# Classes HTML
from .htmlpage import (
    HtmlPage,
    BilingualFormat,
    TagKey,
    FRAGMENT_SEPARATOR,
    VALID_ROOT_TAGS,
    IGNORED_TAGS,
)

# Version du package
__version__ = "0.1.0"

# Exports publics
__all__ = [
    # Version
    "__version__",
    # Classes principales
    "LLM",
    # Segmentation et cache
    "Chunk",
    "Segmentator",
    "Store",
    # Classes HTML
    "HtmlPage",
    "BilingualFormat",
    "TagKey",
    # Constantes
    "FRAGMENT_SEPARATOR",
    "VALID_ROOT_TAGS",
    "IGNORED_TAGS",
    "DEFAULT_OVERLAP_RATIO",
    "DEFAULT_ENCODING",
    "Language",
]
