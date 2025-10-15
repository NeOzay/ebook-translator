"""
Module pour parser et manipuler les pages HTML des fichiers EPUB.

Ce module fournit des outils pour :
- Extraire le texte traduisible des pages HTML
- Grouper les fragments de texte par balise parente
- Remplacer le texte original par sa traduction
- Gérer un cache de pages pour éviter le re-parsing
- Créer des versions bilingues (original + traduction)

Organisation du module :
- constants.py : Constantes (séparateurs, balises valides)
- tag_key.py : Wrapper pour utiliser des Tags BeautifulSoup comme clés
- bilingual.py : Formats d'affichage bilingue
- replacement.py : Méthodes de remplacement de texte dans le DOM
- page.py : Classe principale HtmlPage

Exports publics :
    Classes :
        - HtmlPage : Classe principale pour manipuler les pages HTML
        - TagKey : Wrapper pour clés de dictionnaire basées sur Tags
        - BilingualFormat : Énumération des formats bilingues

    Constantes :
        - FRAGMENT_SEPARATOR : Séparateur de fragments ('</>`)
        - VALID_ROOT_TAGS : Balises racines valides (p, h1-h6)
        - IGNORED_TAGS : Balises à ignorer (script, style)

    Fonctions :
        - get_files : Générateur pour extraire tous les textes des EPUBs
        - find_root_tag : Trouve la balise racine valide
"""

# Constantes
from .constants import (
    FRAGMENT_SEPARATOR,
    VALID_ROOT_TAGS,
    IGNORED_TAGS,
)

# Classes principales
from .tag_key import TagKey
from .bilingual import BilingualFormat
from .page import HtmlPage, get_files

# Fonctions utilitaires
from .replacement import find_root_tag

__all__ = [
    # Constantes
    "FRAGMENT_SEPARATOR",
    "VALID_ROOT_TAGS",
    "IGNORED_TAGS",
    # Classes
    "HtmlPage",
    "TagKey",
    "BilingualFormat",
    # Fonctions
    "get_files",
    "find_root_tag",
]
