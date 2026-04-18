from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

from ebook_translator.config import Config
from ebook_translator.segmentation.helper import count_tokens

from ..htmlpage.page import get_texts
from ..segmentation.chunk import Chunk

if TYPE_CHECKING:
    from ebooklib import epub

    from .chapter_detector import ChapterInfo


@dataclass(kw_only=True)
class ChapterPartChunk(Chunk):
    total_parts: int
    part: int
    chapter: ChapterChunk

    @classmethod
    def from_chunk(
        cls,
        chunk: Chunk,
        chapter: ChapterChunk,
        total_parts: int,
    ) -> ChapterPartChunk:
        """
        Crée un ChapterPartChunk à partir d'un Chunk générique.

        Args:
            chunk: Chunk source à convertir
            chapter: ChapterChunk parent (référence)
            total_parts: Nombre total de parties du chapitre splitté

        Returns:
            ChapterPartChunk avec tous les attributs du Chunk source
        """
        if chapter.index >= 100:
            raise ValueError(
                "Chapter index must be less than 100 for proper global indexing."
            )

        index = (
            chapter.index * 100 + chunk.index
        )  # Index global pour tri correct (ex: chapitre 2 partie 3 => 203)
        return cls(
            index=index,
            part=chunk.index,
            head=chunk.head.copy(),
            body=chunk.body.copy(),
            tail=chunk.tail.copy(),
            token_count=chunk.token_count,
            token_encoding=chunk.token_encoding,
            total_parts=total_parts,
            chapter=chapter,
        )

    def is_first(self) -> bool:
        return self.part == 0

    def is_last(self) -> bool:
        return self.part == self.total_parts - 1


@dataclass
class ChapterChunk(Chunk):
    name: str = field(init=False)
    files: list[epub.EpubHtml] = field(init=False)
    files_names: list[str] = field(init=False)

    def __init__(
        self,
        chapter_info: ChapterInfo,
        token_encoding: str = Config.DEFAULT_ENCODING,
    ):
        super().__init__(index=chapter_info.index, token_encoding=token_encoding)
        # Métadonnées du chapitre
        self.name = chapter_info.name
        self.files = chapter_info.files.copy()
        self.files_names = chapter_info.file_names

        # Extraire texte de tous les fichiers du chapitre
        for tag_key, text in get_texts(chapter_info.files):
            self.body[tag_key] = text
            self.token_count += count_tokens(text, token_encoding)

    @override
    def split_chunk(
        self, max_tokens: int, overlap_ratio: float
    ) -> Iterator[ChapterPartChunk]:
        chunks = list(super().split_chunk(max_tokens, overlap_ratio))

        for chunk in chunks:
            yield ChapterPartChunk.from_chunk(chunk, self, len(chunks))
