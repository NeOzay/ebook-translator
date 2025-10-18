"""
Module de traduction d'ebooks via LLM.

Ebook Translator est un outil qui traduit des fichiers EPUB en utilisant
des Large Language Models (LLM) compatibles OpenAI comme DeepSeek.

Le processus de traduction :
1. Charge et parse l'EPUB source
2. Segmente le contenu en chunks limit�s en tokens avec chevauchement
3. Traduit chaque chunk via l'API LLM (avec cache sur disque)
4. Reconstruit l'EPUB traduit avec les m�tadonn�es originales

Fonctionnalit�s principales :
- Support des formats bilingues (original + traduction)
- Cache persistant des traductions (�vite les retraductions)
- Traitement parall�le des chunks
- Pr�servation de la structure HTML et des m�tadonn�es EPUB
- Logs d�taill�s de chaque requ�te LLM

Organisation du package :
- llm.py : Client LLM avec templates Jinja2 et logging
- segment.py : Segmentation du contenu en chunks avec overlap
- store.py : Cache persistant des traductions (JSON)
- worker.py : Traitement parall�le des chunks
- htmlpage/ : Parsing et manipulation des pages HTML
- translation/ : Orchestration compl�te de la traduction

Exports publics :
    Classes principales :
        - LLM : Client pour les API LLM (DeepSeek, OpenAI, etc.)
        - EpubTranslator : Orchestrateur de traduction d'EPUB
        - TranslationEngine : Moteur de traduction de chunks
        - TranslationWorker : Worker pour traduction parall�le
        - Store : Cache persistant des traductions
        - Segmentator : Segmentation du contenu en chunks

    Classes HTML :
        - HtmlPage : Manipulation des pages HTML
        - BilingualFormat : Formats d'affichage bilingue
        - TagKey : Wrapper pour utiliser Tags comme cl�s

    Dataclasses :
        - Chunk : Repr�sente un morceau de contenu � traduire
        - Language : �num�ration des langues support�es

    Constantes :
        - FRAGMENT_SEPARATOR : S�parateur de fragments HTML
        - VALID_ROOT_TAGS : Balises HTML valides pour traduction
        - DEFAULT_OVERLAP_RATIO : Ratio de chevauchement entre chunks
        - DEFAULT_ENCODING : Encodage tiktoken par d�faut

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

Usage avanc� avec cache et format bilingue :
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
    ...     max_concurrent=3,  # Traduction parall�le
    ...     bilingual_format=BilingualFormat.INLINE
    ... )

Configuration :
    Le module n�cessite une cl� API LLM. Cr�ez un fichier .env :

        DEEPSEEK_API_KEY=sk-votre-cle-ici
        DEEPSEEK_URL=https://api.deepseek.com

    Voir .env.example et CLAUDE.md pour plus de d�tails.

Version: 0.1.0
Author: NeOzay
License: � d�finir
"""

# Classes LLM et traduction
from .llm import LLM
from .translation import EpubTranslator, TranslationEngine
from .translation.translator import Language

# Classes de segmentation et cache
from .segment import Chunk, Segmentator, DEFAULT_OVERLAP_RATIO, DEFAULT_ENCODING
from .store import Store
from .worker import TranslationWorker

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
    "EpubTranslator",
    "TranslationEngine",
    "TranslationWorker",
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
]
