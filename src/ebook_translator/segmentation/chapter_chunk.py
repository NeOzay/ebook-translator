from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ebook_translator.config import Config
from ebook_translator.segmentation.helper import count_tokens, safe_copy

from ..htmlpage.page import get_texts
from ..segmentation import Chunk

if TYPE_CHECKING:
    from ebooklib import epub  # pyright: ignore[reportMissingTypeStubs]

    from ..segmentation.sequential_detector import ChapterGroup


@dataclass(kw_only=True)
class ChapterPartChunk(Chunk):
    total_parts: int
    chapter: "ChapterChunk"

    @classmethod
    def from_chunk(cls, chunk: "Chunk", chapter: "ChapterChunk", total_parts: int):
        data = safe_copy(chunk.__dict__)
        data["total_parts"] = total_parts
        data["chapter"] = chapter
        return cls(**data)

    def is_first(self) -> bool:
        return self.index == 0

    def is_last(self) -> bool:
        return self.index == self.total_parts - 1


@dataclass
class ChapterChunk(Chunk):
    name: str = field(init=False)
    files: list["epub.EpubHtml"] = field(init=False)
    files_names: list[str] = field(init=False)

    def __init__(
        self,
        chapter_group: "ChapterGroup",
        token_encoding: str = Config.DEFAULT_ENCODING,
    ):
        super().__init__(
            index=chapter_group.chapter_index, token_encoding=token_encoding
        )
        # Métadonnées du chapitre
        self.name = chapter_group.chapter_name
        self.files = chapter_group.html_files.copy()
        self.files_names = chapter_group.get_file_names()

        # Extraire texte de tous les fichiers du chapitre
        for tag_key, text in get_texts(chapter_group.html_files):
            self.body[tag_key] = text
            self.token_count += count_tokens(text, token_encoding)

    def split_chunk(
        self, max_tokens: int, overlap_ratio: float
    ) -> Iterator[ChapterPartChunk]:
        chunks = list(super().split_chunk(max_tokens, overlap_ratio))

        for chunk in chunks:
            yield ChapterPartChunk.from_chunk(chunk, self, len(chunks))
