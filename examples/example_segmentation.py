from pathlib import Path

from ebooklib import epub

from ebook_translator.segmentation.segmentator import Segmentator
from ebook_translator.translation.epub_handler import extract_html_items_in_spine_order

source_epub = Path(
    "books/Chillin' in Another World With Level 2 Super Cheat Powers - Volume 02 [J-Novel Club][Premium].epub"
)
source_book = epub.read_epub(source_epub)
html_items, target_book = extract_html_items_in_spine_order(source_book)

segmentator = Segmentator(html_items, 2000)

test = list(segmentator.get_all_segments())

test2 = list(test[0].split_chunk(200, 0))
print(test)
