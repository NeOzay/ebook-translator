from pathlib import Path

from ebooklib import epub

from ebook_translator.segmentation.segmentator import Segmentator
from ebook_translator.translation.epub_handler import extract_html_items_in_spine_order

source_epub = Path("./books/The Yellow Wallpaper.epub")
source_book = epub.read_epub(source_epub)
html_items, target_book = extract_html_items_in_spine_order(source_book)

segmentator = Segmentator(html_items, 2000)

test = list(segmentator.get_all_chapters_by_spine())
display = dict((chunk.name, chunk.files_names) for chunk in test)
test2 = list(test[0].split_chunk(4000, 0.15))
print(display)
