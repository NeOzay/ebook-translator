from ebooklib import epub
from ebook_translator.segment import Segmentator
from ebook_translator.translation.epub_handler import extract_html_items_in_spine_order

epub_path = "./books/Chillin' in Another World With Level 2 Super Cheat Powers - Volume 01 [J-Novel Club][Premium].epub"
source_book = epub.read_epub(epub_path)
html_items, target_book = extract_html_items_in_spine_order(source_book)
segmentator = Segmentator(html_items, 300, overlap_ratio=2)

list_of_segments = list(segmentator.get_all_segments())
print(f"Nombre total de segments extraits : {len(list_of_segments)}")
