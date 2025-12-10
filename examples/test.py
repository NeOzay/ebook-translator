import re

from ebooklib import epub  # type: ignore

from ebook_translator.translation.epub_handler import extract_html_items_in_spine_order


def extract_title(html_content: str) -> str | None:
    """Extrait le titre d'un contenu HTML donné."""
    reg = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
    match = reg.search(html_content)
    if match:
        return match.group(1).strip()
    return None


def extract_titles_from_epub(html_items: list[epub.EpubHtml]) -> list[str]:
    """Extrait et affiche les titres des éléments HTML dans l'ordre de la structure du livre EPUB."""
    titles: list[str] = []
    for item in html_items:
        title = extract_title(item.content.decode("utf-8"))  # type: ignore
        titles.append(title if title else "No Title")
    return titles


source_book = epub.read_epub(
    "./books/Mushoku Tensei - Jobless Reincarnation Volume-1.epub"
)  # type: ignore
html_items, target_book = extract_html_items_in_spine_order(source_book)
titles = extract_titles_from_epub(html_items)
print(f"Found {len(html_items)} HTML items in spine order:")
for i, (title, item) in enumerate(zip(titles, html_items, strict=True)):
    print(f"{i+1}: {item.get_name()} with title '{title}'")
