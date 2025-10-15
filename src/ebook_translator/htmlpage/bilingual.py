"""
Formatage et gestion des textes bilingues (original + traduction).
"""

from enum import Enum


class BilingualFormat(Enum):
    """
    Formats disponibles pour l'affichage du texte bilingue.

    DISABLE: Désactive le mode bilingue, remplace complètement l'original
    INLINE: Original et traduction sur la même ligne séparés par " | "
    SEPARATE_TAG: Crée une balise séparée après l'original (recommandé)
    RUBY: Utilise les balises HTML <ruby> pour afficher la traduction au-dessus
    """

    DISABLE = "disable"
    INLINE = "inline"
    SEPARATE_TAG = "separate_tag"


def format_bilingual_inline(original: str, translation: str) -> str:
    """
    Formate le texte original et sa traduction pour le format INLINE uniquement.

    Note: Cette fonction est uniquement utilisée pour le format INLINE.
    Les formats SEPARATE_TAG et RUBY utilisent des méthodes dédiées qui créent
    de vraies balises HTML.

    Args:
        original: Le texte original
        translation: Le texte traduit

    Returns:
        Texte formaté combinant original et traduction avec séparateur " | "

    Example:
        >>> format_bilingual_inline("Hello", "Bonjour")
        "Hello | Bonjour"
    """
    return f"{original} | {translation}"
