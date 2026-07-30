"""Extraction des titres `<title>` bruts d'un EPUB, dans l'ordre du spine.

Montre la vue **source** : ce que déclare chaque fichier HTML, sans passer par
la détection de chapitres. Pour la vue du détecteur — qui regroupe les fichiers
en chapitres et croise la table des matières — voir `example_chapter_names.py`.
"""

import re
from pathlib import Path

from ebooklib import epub

from ebook_translator.translation.epub_handler import extract_html_items_in_spine_order

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def extract_title(html_content: str) -> str | None:
    """Extrait le titre d'un contenu HTML donné.

    Args:
        html_content: Contenu HTML décodé de l'item EPUB.

    Returns:
        Le texte de la balise `<title>`, ou None si elle est absente.
    """
    match = _TITLE_RE.search(html_content)
    return match.group(1).strip() if match else None


def extract_titles_from_epub(html_items: list[epub.EpubHtml]) -> list[str]:
    """Extrait les titres des items HTML dans l'ordre du spine.

    Args:
        html_items: Items HTML dans l'ordre du spine.

    Returns:
        Un titre par item, "No Title" si la balise est absente.
    """
    titles: list[str] = []
    for item in html_items:
        title = extract_title(item.content.decode("utf-8"))  # type: ignore
        titles.append(title if title else "No Title")
    return titles


def main() -> None:
    """Affiche les titres de l'EPUB de test."""
    source_epub = Path("tests/Saint-Exupery-Le_Petit_Prince.epub")
    source_book = epub.read_epub(source_epub)  # type: ignore
    html_items, _target_book = extract_html_items_in_spine_order(source_book)
    titles = extract_titles_from_epub(html_items)

    print(f"Found {len(html_items)} HTML items in spine order:")
    for i, (title, item) in enumerate(zip(titles, html_items, strict=True)):
        print(f"{i + 1}: {item.get_name()} with title '{title}'")


if __name__ == "__main__":
    main()
