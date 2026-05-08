"""
Module de segmentation du contenu EPUB en chunks pour la traduction.

Ce module gère la segmentation intelligente du contenu d'un EPUB en morceaux
de taille limitée (en tokens) pour la traduction par LLM. Il préserve le
contexte entre les chunks via un système de chevauchement (overlap).
"""

from collections.abc import Generator, Iterable, Iterator
from typing import TYPE_CHECKING, Literal

from ebooklib import epub

from ebook_translator.config import Config
from ebook_translator.segmentation.helper import turn_resource_to_chunks
from ebook_translator.translation.epub_handler import get_html_items_in_spine_order

from ..constants import DEFAULT_OVERLAP_RATIO
from ..htmlpage import get_texts
from ..logger import get_logger
from .chunk import Chunk

if TYPE_CHECKING:
    from ..segmentation.chapter_chunk import ChapterChunk
    from .chapter_detector import SequentialDetectorConfig

logger = get_logger(__name__)


class Segmentator:
    """
    Segmente le contenu d'un EPUB en chunks de taille limitée en tokens.

    Cette classe divise intelligemment le contenu de plusieurs fichiers HTML
    en morceaux (chunks) qui respectent une limite de tokens, avec un système
    de chevauchement (overlap) pour préserver le contexte entre les chunks.

    Le chevauchement fonctionne ainsi :
    - Le début du chunk N+1 contient du contexte du chunk N (head)
    - La fin du chunk N contient du contexte pour le chunk N+1 (tail)

    Attributes:
        epub_htmls: Liste des pages HTML de l'EPUB à segmenter
        max_tokens: Nombre maximum de tokens par chunk
        overlap_ratio: Ratio de chevauchement entre chunks (défaut: 0.15 = 15%)
        _encoding: Encodeur tiktoken pour compter les tokens

    Example:
        >>> segmentator = Segmentator(epub_htmls, max_tokens=2000)
        >>> for chunk in segmentator.get_all_segments():
        ...     translation = llm.translate(str(chunk))
        ...     for page, tag, text in chunk.fetch():
        ...         page.replace_text(tag, translation)
    """

    def __init__(
        self,
        epub_source: epub.EpubBook | list[epub.EpubHtml],
        max_tokens: int,
        overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
        head_tail_balance: float = 0.75,
        encoding: str = Config.DEFAULT_ENCODING,
    ) -> None:
        """
        Initialise le segmentateur.

        Args:
            epub_source: Soit un EpubBook (TOC-aware), soit une liste d'EpubHtml
            max_tokens: Nombre maximum de tokens par chunk
            overlap_ratio: Ratio de chevauchement
                - Si < 1.0 : pourcentage de max_tokens (ex: 0.15 = 15%)
                - Si >= 1.0 : multiple de max_tokens (ex: 2.0 = 200% = 2× max_tokens)
            encoding: Nom de l'encodage tiktoken à utiliser

        Note:
            Un overlap_ratio >= 1.0 créera un contexte étendu qui peut englober
            plusieurs chunks précédents. Cela augmente la cohérence mais aussi
            la consommation de tokens et le coût des requêtes LLM.
        """
        if isinstance(epub_source, epub.EpubBook):
            self._book: epub.EpubBook | None = epub_source
            self.epub_htmls = get_html_items_in_spine_order(epub_source)
        else:
            self._book = None
            self.epub_htmls = epub_source

        self.max_tokens = max_tokens
        self.overlap_ratio = overlap_ratio
        self.head_tail_balance = head_tail_balance
        self.encoding = encoding

        # Warning si overlap_ratio >= 1.0 (contexte très étendu)
        if overlap_ratio >= 1.0:
            overlap_tokens = int(max_tokens * overlap_ratio)
            logger.warning(
                f"⚠️ Overlap ratio très élevé : {overlap_ratio:.1f} "
                f"({overlap_tokens} tokens d'overlap pour {max_tokens} tokens de body). "
                f"Cela augmentera significativement la consommation de tokens et le coût des traductions."
            )

    def get_all_segments(
        self,
        segmentation_logic: Literal["stop_at_end_of_chapter", "continue"] = "continue",
    ) -> Generator[Chunk]:
        """
        Génère tous les chunks en segmentant le contenu de l'EPUB.

        Cette méthode parcourt tous les fragments de texte des pages HTML
        et les regroupe en chunks respectant la limite de tokens. Elle gère
        automatiquement le chevauchement entre chunks pour préserver le contexte.

        Le système de chevauchement (overlap) fonctionne ainsi :
        - overlap_ratio < 1.0 : Pourcentage de max_tokens (ex: 0.15 = 15%)
        - overlap_ratio >= 1.0 : Multiple de max_tokens (ex: 1.5 = 150% du body)

        Avec overlap_ratio > 1.0, le contexte peut s'étendre sur plusieurs chunks
        précédents. Par exemple, avec overlap_ratio=2.0 et max_tokens=2000 :
        - Chunk 0 : body=2000 tokens, head=[], tail=4000 tokens
        - Chunk 1 : body=2000 tokens, head=4000 tokens (depuis chunk 0), tail=4000 tokens
        - Le head de chunk 1 peut inclure tout le body de chunk 0 + du contexte antérieur

        Args:
            segmentation_logic: Stratégie de segmentation.
                - `"continue"` (défaut) : segmente l'EPUB en flux continu, les
                  chunks peuvent chevaucher les frontières de chapitres.
                - `"stop_at_end_of_chapter"` : redémarre la segmentation à
                  chaque chapitre (détecté via la spine EPUB), garantissant
                  qu'aucun chunk ne chevauche deux chapitres. Utile pour la
                  Phase 0 (analyse littéraire par chapitre).

        Yields:
            Les chunks successifs avec leur contexte (head/tail)

        Example:
            >>> # Overlap standard (15%), flux continu
            >>> segmentator = Segmentator(epub_htmls, max_tokens=2000, overlap_ratio=0.15)
            >>> for chunk in segmentator.get_all_segments():
            ...     print(f"Chunk {chunk.index} with {len(chunk.body)} items")

            >>> # Segmentation par chapitre (Phase 0)
            >>> for chunk in segmentator.get_all_segments("stop_chunk_end_of_chapter"):
            ...     print(f"Chunk {chunk.index}: chapitre isolé")

            >>> # Overlap étendu (200% du body)
            >>> segmentator = Segmentator(epub_htmls, max_tokens=2000, overlap_ratio=2.0)
            >>> for chunk in segmentator.get_all_segments():
            ...     # Le head contient ~4000 tokens de contexte des chunks précédents
            ...     print(f"Chunk {chunk.index}: head={len(chunk.head)}, body={len(chunk.body)}, tail={len(chunk.tail)}")
        """

        def process(resource_iterable: Iterable[epub.EpubHtml]) -> Generator[Chunk]:
            return turn_resource_to_chunks(
                get_texts(resource_iterable),
                self.max_tokens,
                self.overlap_ratio,
                self.encoding,
                head_tail_balance=self.head_tail_balance,
            )

        if segmentation_logic == "stop_at_end_of_chapter":
            for chapter in self.get_all_chapters_by_spine():
                yield from chapter.split_chunk(
                    self.max_tokens, self.overlap_ratio, self.head_tail_balance
                )
            return

        yield from process(self.epub_htmls)

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        overlap_tokens = self.max_tokens * self.overlap_ratio

        # Affichage différent selon si overlap < ou >= max_tokens
        if self.overlap_ratio < 1.0:
            overlap_str = f"{self.overlap_ratio * 100:.0f}% ({overlap_tokens} tokens)"
        else:
            overlap_str = (
                f"{self.overlap_ratio:.1f}× max_tokens ({overlap_tokens} tokens)"
            )

        return (
            f"Segmentator("
            f"pages={len(self.epub_htmls)}, "
            f"max_tokens={self.max_tokens}, "
            f"overlap={overlap_str})"
        )

    def get_all_chapters_by_spine(
        self,
        config: SequentialDetectorConfig | None = None,
    ) -> Iterator[ChapterChunk]:
        """
        Génère chunks par chapitre basé sur analyse de la spine EPUB.

        Plus robuste que get_all_chapters() (balises h1) car :
        - Utilise structure EPUB (spine + noms de fichiers)
        - Supporte chapitres multi-fichiers (chapter1 + chapter1_a + insert1)
        - Patterns avancés : chapter11 = subpart, inserts intercalés
        - Fallback LLM pour cas ambigus (ancien détecteur uniquement)

        Args:
            config: Configuration du détecteur séquentiel
                (voir SequentialDetectorConfig pour les options)
        Yields:
            Un Chunk par chapitre détecté
        """
        from .chapter import Chapters

        if self._book is not None:
            chapters = Chapters(self._book, config=config)
        else:
            chapters = Chapters.from_html_items(self.epub_htmls, config=config)

        yield from chapters.iter_chapter_chunks(encoding=self.encoding)
