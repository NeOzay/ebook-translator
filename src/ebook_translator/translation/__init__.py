"""
Module de traduction d'ebooks utilisant des LLM.

Ce module fournit tous les outils nécessaires pour traduire des fichiers EPUB
de bout en bout, incluant :
- Gestion des fichiers EPUB (lecture, métadonnées, reconstruction)
- Moteur de traduction avec cache
- Orchestration complète du processus

Le parsing du format `<N/>...[=[END]=]` n'est plus ici : il appartient à
`template.phase.translation_models.LineIndexedLLMResponse`, qui en est la
source de vérité unique.

Organisation du module :
- epub_handler.py : Fonctions de gestion des fichiers EPUB
- engine.py : Moteur de traduction des chunks + fonctions de mapping
- translator.py : Orchestration complète

Exports publics :
    Fonctions EPUB :
        - copy_epub_metadata : Copie les métadonnées
        - extract_html_items_in_spine_order : Extraction du contenu
        - reconstruct_html_item : Reconstruction après traduction

    Fonctions de traduction :
        - build_translation_map : Construit le mapping des traductions

Usage :
    >>> from ebook_translator.translation import build_translation_map
    >>>
    >>> # Mapper traductions d'un chunk
    >>> translation_map = build_translation_map(chunk, translated_texts)
"""

# Fonctions principales
from .engine import build_translation_map

# Fonctions EPUB
from .epub_handler import (
    copy_epub_metadata,
    extract_html_items_in_spine_order,
    get_html_items_in_spine_order,
    reconstruct_html_item,
)

__all__ = [
    # Fonctions principales
    "build_translation_map",
    # Fonctions EPUB
    "copy_epub_metadata",
    "extract_html_items_in_spine_order",
    "get_html_items_in_spine_order",
    "reconstruct_html_item",
]
