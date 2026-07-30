"""
Gestion des chapitres et mapping Chunk ↔ Chapitre.

Ce module fournit :
- Re-export de ChapterInfo depuis chapter_detector
- Classe Chapters : point d'entrée unique pour la détection et l'accès aux chapitres
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterator
from typing import TYPE_CHECKING

from ebook_translator.config import Config
from ebook_translator.logger import get_logger
from ebook_translator.segmentation.chapter_chunk import ChapterPartChunk
from ebook_translator.segmentation.chapter_detector import (
    ChapterInfo,  # re-export pour __init__.py
    SequentialChapterDetector,
    SequentialDetectorConfig,
    extract_toc_map,
)
from template.phase.analyze_chapter_layered_models import AnalyseChapter

if TYPE_CHECKING:
    from ebooklib import epub

    from ebook_translator.segmentation import Chunk

    from .chapter_chunk import ChapterChunk

logger = get_logger(__name__)

type AnalysisLookup = Callable[[str], AnalyseChapter | None]
"""Lecture d'une fiche Phase 0 par nom de chapitre.

Injecté dans `Chapters` pour que `segmentation` ne dépende ni du
`StoreManager`, ni du `ByteStore`, ni du persister de Phase 0 — seule la
phase qui écrit ces fiches sait les relire.
"""

__all__ = ["AnalysisLookup", "ChapterInfo", "Chapters"]


def _extract_spine_items(book: epub.EpubBook) -> list[epub.EpubHtml]:
    """Extrait les items HTML dans l'ordre du spine.

    Args:
        book: Livre EPUB source

    Returns:
        Liste des items HTML dans l'ordre du spine
    """
    from ebook_translator.translation.epub_handler import get_html_items_in_spine_order

    return get_html_items_in_spine_order(book)


def _extract_toc_names(book: epub.EpubBook) -> dict[str, str]:
    """Construit {normalized_filename: title} depuis book.toc.

    Args:
        book: Livre EPUB source

    Returns:
        Mapping {normalized_filename: title}
    """
    return extract_toc_map(book.toc)  # type: ignore[arg-type]


def _build_chapters(
    html_items: list[epub.EpubHtml],
    toc_names: dict[str, str],
    config: SequentialDetectorConfig | None,
) -> tuple[list[ChapterInfo], dict[str, ChapterInfo]]:
    """Lance le détecteur et construit les index.

    Args:
        html_items: Liste des items HTML dans l'ordre du spine
        toc_names: Mapping {normalized_filename: title} depuis le TOC
        config: Configuration optionnelle du détecteur

    Returns:
        Tuple (liste de ChapterInfo, dict {file_name: ChapterInfo})
    """
    detector = SequentialChapterDetector(html_items, config=config, toc_map=toc_names)
    infos = list(detector.detect_chapters())
    file_to_info = {name: info for info in infos for name in info.file_names}
    return infos, file_to_info


class Chapters:
    """Point d'entrée unique pour la détection et l'accès aux chapitres.

    La liste de chapitres est calculée une seule fois à la construction et
    mise en cache dans `_infos`. Toutes les méthodes s'appuient sur ce cache.

    Example:
        >>> chapters = Chapters(book, store_manager)
        >>>
        >>> # Itérer sur les chunks de chapitres
        >>> for chunk in chapters.iter_chapter_chunks():
        ...     print(chunk.name)
        >>>
        >>> # Obtenir l'analyse littéraire applicable
        >>> analysis = chapters.get_literary_analysis(chunk)
        >>> if analysis:
        ...     print(analysis["résumé"])
    """

    def __init__(
        self,
        book: epub.EpubBook,
        analysis_lookup: AnalysisLookup | None = None,
        config: SequentialDetectorConfig | None = None,
    ) -> None:
        """Initialise le gestionnaire de chapitres depuis un EpubBook.

        Args:
            book: Livre EPUB source (fournit spine + TOC)
            analysis_lookup: Accès aux fiches Phase 0, par nom de chapitre
                (typiquement `LiteraryAnalysisPhase.latest_analysis_for`).
                `None` si Phase 0 n'est pas dans le pipeline.
            config: Configuration optionnelle du détecteur
        """
        self._analysis_lookup = analysis_lookup
        html_items = _extract_spine_items(book)
        toc_names = _extract_toc_names(book)
        self._infos, self._file_to_info = _build_chapters(html_items, toc_names, config)

    @classmethod
    def from_html_items(
        cls,
        html_items: list[epub.EpubHtml],
        analysis_lookup: AnalysisLookup | None = None,
        config: SequentialDetectorConfig | None = None,
    ) -> Chapters:
        """Construit depuis une liste de fichiers HTML (sans accès au TOC).

        Args:
            html_items: Liste des items HTML dans l'ordre du spine
            analysis_lookup: Accès aux fiches Phase 0, par nom de chapitre
                (cf. `__init__`)
            config: Configuration optionnelle du détecteur

        Returns:
            Instance de Chapters sans informations TOC
        """
        instance = object.__new__(cls)
        instance._analysis_lookup = analysis_lookup
        instance._infos, instance._file_to_info = _build_chapters(
            html_items, {}, config
        )
        return instance

    def get_chapters(self) -> list[ChapterInfo]:
        """Retourne la liste des chapitres détectés (cache).

        Returns:
            Liste des ChapterInfo détectés
        """
        return self._infos

    def iter_chapter_chunks(
        self, encoding: str = Config.DEFAULT_ENCODING
    ) -> Generator[ChapterChunk]:
        """Génère un ChapterChunk par chapitre (non vide).

        Args:
            encoding: Encodage tiktoken pour compter les tokens

        Yields:
            ChapterChunk pour chaque chapitre ayant du contenu
        """
        from .chapter_chunk import ChapterChunk

        for info in self._infos:
            chunk = ChapterChunk(info, token_encoding=encoding)
            if chunk.body:
                yield chunk

    def get_chapter_for_chunk(self, chunk: Chunk) -> ChapterInfo | None:
        """Retourne les métadonnées du chapitre contenant ce chunk.

        Stratégie :
        1. Si ChapterPartChunk : utiliser chunk.chapter.files_names
        2. Sinon : chercher via chunk.scope (file_name, line_number)

        Args:
            chunk: Chunk à analyser

        Returns:
            ChapterInfo du chapitre, ou None si non trouvé
        """
        # Cas 1 : ChapterPartChunk avec attribut .chapter
        if isinstance(chunk, ChapterPartChunk):
            for name in chunk.chapter.files_names:
                if name in self._file_to_info:
                    return self._file_to_info[name]

        # Cas 2 : Chunk classique → chercher via scope
        for file_name, _ in chunk.scope:
            if file_name in self._file_to_info:
                return self._file_to_info[file_name]

        return None

    def get_literary_analysis(self, chunk: Chunk) -> AnalyseChapter | None:
        """Récupère l'analyse littéraire applicable à ce chunk.

        Résout le chapitre du chunk, puis délègue la lecture du cache au
        `analysis_lookup` fourni à la construction — c'est Phase 0 qui sait
        où et comment ses fiches sont stockées.

        Args:
            chunk: Chunk à analyser

        Returns:
            Analyse littéraire (`AnalyseChapter`), ou `None` si Phase 0 est
            absente du pipeline ou n'a pas tourné sur ce chapitre.
        """
        if self._analysis_lookup is None:
            return None

        chapter_info = self.get_chapter_for_chunk(chunk)
        if chapter_info is None:
            return None

        return self._analysis_lookup(chapter_info.name)

    def __len__(self) -> int:
        return len(self._infos)

    def __iter__(self) -> Iterator[ChapterInfo]:
        return iter(self._infos)
