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
    Fonctions EPUB :
        - copy_epub_metadata : Copie les métadonnées
        - extract_html_items_in_spine_order : Extraction du contenu
        - reconstruct_html_item : Reconstruction après traduction

    Fonctions de traduction :
        - parse_llm_translation_output : Parse les sorties LLM
        - build_translation_map : Construit le mapping des traductions

Usage :
    >>> from ebook_translator.translation import build_translation_map
    >>> from ebook_translator.translation import parse_llm_translation_output
    >>>
    >>> # Mapper traductions d'un chunk
    >>> translation_map = build_translation_map(chunk, translated_texts)
    >>>
    >>> # Parser sortie LLM
    >>> translations = parse_llm_translation_output(llm_output)
"""

# Fonctions principales
from .engine import build_translation_map
from .parser import parse_llm_translation_output

# Fonctions EPUB
from .epub_handler import (
    copy_epub_metadata,
    extract_html_items_in_spine_order,
    reconstruct_html_item,
)

__all__ = [
    # Fonctions principales
    "parse_llm_translation_output",
    "build_translation_map",
    # Fonctions EPUB
    "copy_epub_metadata",
    "extract_html_items_in_spine_order",
    "reconstruct_html_item",
]
