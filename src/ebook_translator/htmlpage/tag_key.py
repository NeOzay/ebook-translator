"""
Wrapper pour utiliser des Tags BeautifulSoup comme clés de dictionnaire.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from bs4.element import Tag

if TYPE_CHECKING:
    from .page import HtmlPage


class TagKey:
    """
    Wrapper pour utiliser des Tags BeautifulSoup comme clés de dictionnaire.

    Cette classe utilise l'identité de l'objet (id()) plutôt que l'égalité
    de contenu pour la comparaison. Cela permet d'avoir deux tags avec le
    même contenu HTML comme clés distinctes dans un dictionnaire.

    Attributes:
        tag: Le tag BeautifulSoup encapsulé
        _id: L'identité unique de l'objet tag (résultat de id())
    """

    __slots__ = ("tag", "_id", "index", "page")

    def __init__(self, index: int, tag: Tag, page: HtmlPage) -> None:
        """
        Initialise un TagKey.

        Args:
            tag: Le tag BeautifulSoup à encapsuler
        """
        self.tag = tag
        self._id = id(tag)
        self.index = str(index)
        self.page = page

    def __hash__(self) -> int:
        """Retourne le hash basé sur l'identité de l'objet."""
        return self._id

    def __eq__(self, other: object) -> bool:
        """
        Compare deux TagKey par identité d'objet.

        Args:
            other: L'objet à comparer

        Returns:
            True si les deux TagKey encapsulent le même objet Tag
        """
        if not isinstance(other, TagKey):
            return False
        return self.tag is other.tag

    def __repr__(self) -> str:
        """Représentation en chaîne pour le debug."""
        return f"TagKey(index={self.index}, tag={self.tag.name}, page={self.page.epub_html.file_name})"
