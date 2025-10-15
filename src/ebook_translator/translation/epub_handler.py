"""
Gestion des fichiers EPUB : lecture, métadonnées, extraction et reconstruction.
"""

from typing import TYPE_CHECKING, Literal

from bs4 import BeautifulSoup
from ebooklib import epub, ITEM_DOCUMENT

if TYPE_CHECKING:
    from ebooklib.epub import EpubBook, EpubHtml


def copy_epub_metadata(
    source_book: "EpubBook", target_book: "EpubBook", target_language: str
) -> None:
    """
    Copie les métadonnées d'un EPUB source vers un EPUB cible.

    Args:
        source_book: L'EPUB source
        target_book: L'EPUB cible à remplir
        target_language: Code de la langue cible (ex: "fr", "en")
    """
    # Copier l'identifiant
    identifier_metadata = source_book.get_metadata("DC", "identifier")
    if identifier_metadata:
        target_book.set_identifier(identifier_metadata[0][0])

    # Copier et modifier le titre
    title_metadata = source_book.get_metadata("DC", "title")
    if title_metadata:
        original_title = title_metadata[0][0]
        target_book.set_title(f"{original_title} ({target_language})")

    # Définir la langue cible
    target_book.set_language(target_language)

    # Copier les auteurs
    for author in source_book.get_metadata("DC", "creator"):
        target_book.add_author(author[0])

    # Copier la table des matières et le spine
    target_book.toc = source_book.toc
    target_book.spine = source_book.spine


def extract_html_items_in_spine_order(
    book: "EpubBook",
) -> tuple[list["EpubHtml"], "EpubBook"]:
    """
    Extrait les items HTML d'un EPUB dans l'ordre du spine et prépare un nouveau livre.

    Args:
        book: L'EPUB source

    Returns:
        Tuple contenant:
        - Liste des items HTML dans l'ordre du spine
        - Un nouvel EpubBook avec les items non-document copiés
    """
    new_book = epub.EpubBook()
    spine_order = [spine[0] for spine in book.spine]
    html_items: list[epub.EpubHtml] = []

    for item in book.get_items():
        if item.get_type() == ITEM_DOCUMENT:
            # Insérer à la position correcte selon le spine
            insert_position = spine_order.index(item.id)
            html_items.insert(insert_position, item)
        else:
            # Copier les ressources non-document (images, CSS, etc.)
            new_book.add_item(item)

    return html_items, new_book


def reconstruct_html_item(item: "EpubHtml") -> None:
    """
    Reconstruit le contenu HTML d'un item EPUB après traduction.

    Cette fonction parse le HTML, extrait le body et les liens,
    puis met à jour le contenu de l'item.

    Args:
        item: L'item EPUB dont le contenu doit être reconstruit
    """
    soup = BeautifulSoup(item.content, "html.parser")

    # Extraire et encoder le body
    body = soup.find("body")
    if body:
        item.set_content(body.encode("utf-8"))

    # Extraire et ajouter les liens CSS
    link = soup.find("link")
    if link:
        link_attrs: dict[Literal["rel", "href", "type"], str | None] = {}
        for attr_name in ("rel", "href", "type"):
            attr_value = link.get(attr_name)
            if isinstance(attr_value, list):
                link_attrs[attr_name] = attr_value[0]
            else:
                link_attrs[attr_name] = attr_value

        if link_attrs:
            item.add_link(**link_attrs)
