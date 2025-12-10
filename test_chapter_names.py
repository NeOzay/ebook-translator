"""Script de test pour afficher les noms de chapitres détectés."""

from pathlib import Path

from ebooklib import epub  # pyright: ignore[reportMissingTypeStubs]

from ebook_translator.segmentation.segmentator import Segmentator
from ebook_translator.translation.epub_handler import extract_html_items_in_spine_order

source_epub = Path("books/Mushoku Tensei - Jobless Reincarnation Volume-1.epub")
source_book = epub.read_epub(source_epub)  # pyright: ignore[reportUnknownMemberType]
html_items, target_book = extract_html_items_in_spine_order(source_book)

segmentator = Segmentator(html_items, 2000)

print("=" * 80)
print("Chapitres détectés par SequentialChapterDetector:")
print("=" * 80)

chapters = list(segmentator.get_all_chapters_by_spine())

for chunk in chapters:
    files_str = ", ".join(chunk.files_names)
    print(f"\n{chunk.name}")
    print(f"  Fichiers: {files_str}")

print("\n" + "=" * 80)
print(f"Total: {len(chapters)} chapitres détectés")
print("=" * 80)
