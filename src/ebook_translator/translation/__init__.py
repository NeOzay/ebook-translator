"""
Module de traduction d'ebooks utilisant des LLM.

Ce module fournit tous les outils nécessaires pour traduire des fichiers EPUB
de bout en bout, incluant :
- Gestion des fichiers EPUB (lecture, métadonnées, reconstruction)
- Parsing des sorties LLM
- Moteur de traduction avec cache
- Orchestration complète du processus

Organisation du module :
- epub_handler.py : Fonctions de gestion des fichiers EPUB
- parser.py : Fonction de parsing des sorties LLM
- engine.py : Moteur de traduction des chunks + fonctions de mapping
- translator.py : Orchestration complète

Exports publics :
    Classes :
        - EpubTranslator : Orchestrateur de traduction d'EPUB
        - TranslationEngine : Moteur de traduction des chunks

    Fonctions EPUB :
        - copy_epub_metadata : Copie les métadonnées
        - extract_html_items_in_spine_order : Extraction du contenu
        - reconstruct_html_item : Reconstruction après traduction

    Fonctions de traduction :
        - parse_llm_translation_output : Parse les sorties LLM
        - build_translation_map : Construit le mapping des traductions
        - flatten_translation_map : Aplatit un mapping hiérarchique

Usage :
    >>> from ebook_translator.translation import EpubTranslator
    >>> from ebook_translator.llm import LLM
    >>>
    >>> # Traduction complète d'un EPUB
    >>> llm = LLM(model_name="deepseek-chat", api_key="...", max_tokens=1300)
    >>> translator = EpubTranslator(llm)
    >>> translator.translate(
    ...     epub_path="input.epub",
    ...     output_epub="output.epub",
    ...     target_language="fr",
    ...     max_concurrent=1
    ... )
    >>>
    >>> # Traduction de chunk uniquement
    >>> from ebook_translator.translation import TranslationEngine
    >>> from ebook_translator.store import Store
    >>> from ebook_translator.htmlpage import BilingualFormat
    >>>
    >>> store = Store()
    >>> engine = TranslationEngine(llm, store, "fr")
    >>> engine.translate_chunk(chunk, bilingual_format=BilingualFormat.SEPARATE_TAG)
"""

# Classes principales
from .translator import EpubTranslator
from .engine import (
    TranslationEngine,
    build_translation_map,
    flatten_translation_map,
)
from .parser import parse_llm_translation_output

# Fonctions EPUB
from .epub_handler import (
    copy_epub_metadata,
    extract_html_items_in_spine_order,
    reconstruct_html_item,
)

__all__ = [
    # Classes
    "EpubTranslator",
    "TranslationEngine",
    # Fonctions principales
    "parse_llm_translation_output",
    # Fonctions EPUB
    "copy_epub_metadata",
    "extract_html_items_in_spine_order",
    "reconstruct_html_item",
    # Fonctions de mapping
    "build_translation_map",
    "flatten_translation_map",
]
