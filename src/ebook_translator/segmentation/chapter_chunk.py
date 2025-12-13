from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ebook_translator.config import Config
from ebook_translator.segmentation.helper import count_tokens

from ..htmlpage.page import get_texts
from ..segmentation import Chunk

if TYPE_CHECKING:
    from ebooklib import epub

    from ..segmentation.sequential_detector import ChapterGroup


@dataclass(kw_only=True)
class ChapterPartChunk(Chunk):
    total_parts: int
    chapter: "ChapterChunk"

    @classmethod
    def from_chunk(
        cls,
        chunk: "Chunk",
        chapter: "ChapterChunk",
        total_parts: int,
    ) -> "ChapterPartChunk":
        """
        Crée un ChapterPartChunk à partir d'un Chunk générique.

        Args:
            chunk: Chunk source à convertir
            chapter: ChapterChunk parent (référence)
            total_parts: Nombre total de parties du chapitre splitté

        Returns:
            ChapterPartChunk avec tous les attributs du Chunk source
        """
        return cls(
            index=chunk.index,
            head=chunk.head.copy(),
            body=chunk.body.copy(),
            tail=chunk.tail.copy(),
            token_count=chunk.token_count,
            token_encoding=chunk.token_encoding,
            total_parts=total_parts,
            chapter=chapter,
        )

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
