"""
Tests pour SequentialChapterDetector.

Tests unitaires : normalisation de noms, extraction de numéros,
  détection de skip/front/back matter, logique séquentielle.

Tests d'intégration : détection sur Le Petit Prince (filenames 001-044).
"""

from unittest.mock import Mock

from ebooklib import epub

from ebook_translator.segmentation.chapter_chunk import ChapterChunk
from ebook_translator.segmentation.chapter_detector import (
    SequentialChapterDetector,
    SequentialDetectorConfig,
    _FileType,
)


def make_epub_html(filename: str) -> epub.EpubHtml:
    """Crée un mock epub.EpubHtml avec le nom de fichier donné."""
    mock = Mock(spec=epub.EpubHtml)
    mock.get_name.return_value = filename
    return mock


class TestNormalizeFilename:
    """Tests pour _normalize_filename."""

    def test_strips_path_and_extension(self):
        detector = SequentialChapterDetector([])
        result = detector._normalize_filename("Text/chapter1.xhtml")  # type: ignore[reportPrivateUsage]
        assert result == "chapter1"

    def test_lowercase(self):
        detector = SequentialChapterDetector([])
        result = detector._normalize_filename("Chapter1.HTML")  # type: ignore[reportPrivateUsage]
        assert result == "chapter1"

    def test_bare_filename(self):
        detector = SequentialChapterDetector([])
        result = detector._normalize_filename("001.html")  # type: ignore[reportPrivateUsage]
        assert result == "001"

    def test_no_path(self):
        detector = SequentialChapterDetector([])
        result = detector._normalize_filename("toc.xhtml")  # type: ignore[reportPrivateUsage]
        assert result == "toc"


class TestExtractFilenameAndChapterNumber:
    """Tests pour _extract_filename_and_chapter_number."""

    def test_keyword_with_number(self):
        detector = SequentialChapterDetector([])
        name, num = detector._extract_filename_and_chapter_number("chapter3")  # type: ignore[reportPrivateUsage]
        assert name == "chapter"
        assert num == 3

    def test_keyword_with_separator_and_number(self):
        detector = SequentialChapterDetector([])
        name, num = detector._extract_filename_and_chapter_number("chapter_01")  # type: ignore[reportPrivateUsage]
        assert name == "chapter"
        assert num == 1

    def test_bare_number(self):
        """Numéro pur (≥2 chiffres) → empty_chapter_N."""
        detector = SequentialChapterDetector([])
        name, num = detector._extract_filename_and_chapter_number("004")  # type: ignore[reportPrivateUsage]
        assert name == "empty_chapter_0"
        assert num == 4

    def test_bare_number_increments_index(self):
        """Chaque appel incrémente l'index empty_chapter_N."""
        detector = SequentialChapterDetector([])
        name1, _ = detector._extract_filename_and_chapter_number("001")  # type: ignore[reportPrivateUsage]
        name2, _ = detector._extract_filename_and_chapter_number("002")  # type: ignore[reportPrivateUsage]
        assert name1 == "empty_chapter_0"
        assert name2 == "empty_chapter_1"

    def test_keyword_without_number(self):
        """Mot-clé sans numéro → None comme numéro."""
        detector = SequentialChapterDetector([])
        name, num = detector._extract_filename_and_chapter_number("prologue")  # type: ignore[reportPrivateUsage]
        assert name == "prologue"
        assert num is None


class TestAnalyzeWithContext:
    """Tests pour la détection de types de fichiers."""

    def test_skip_keywords(self):
        """Les fichiers système sont ignorés (SKIP)."""
        detector = SequentialChapterDetector([])
        for filename in ["cover", "toc", "copyright", "colophon"]:
            analysis = detector._analyze_with_context(filename, 0)  # type: ignore[reportPrivateUsage]
            assert analysis.file_type == _FileType.SKIP, (
                f"{filename!r} devrait être SKIP"
            )

    def test_front_matter_ignored_by_default(self):
        """Front matter ignoré par défaut (include_front_matter=False)."""
        detector = SequentialChapterDetector([])
        analysis = detector._analyze_with_context("preface", 0)  # type: ignore[reportPrivateUsage]
        assert analysis.file_type == _FileType.SKIP

    def test_front_matter_included_when_configured(self):
        """Front matter devient chapitre si include_front_matter=True."""
        config = SequentialDetectorConfig(include_front_matter=True)
        detector = SequentialChapterDetector([], config=config)
        analysis = detector._analyze_with_context("preface", 0)  # type: ignore[reportPrivateUsage]
        assert analysis.file_type == _FileType.FRONT_MATTER
        assert analysis.is_new_chapter is True

    def test_back_matter_ignored_by_default(self):
        """Back matter ignoré par défaut."""
        detector = SequentialChapterDetector([])
        analysis = detector._analyze_with_context("afterword", 0)  # type: ignore[reportPrivateUsage]
        assert analysis.file_type == _FileType.SKIP

    def test_insert_is_not_new_chapter(self):
        """Fichier 'insert' est ajouté au chapitre courant (pas nouveau chapitre)."""
        detector = SequentialChapterDetector([])
        # Le nom normalisé doit commencer par "insert" pour déclencher INSERT
        analysis = detector._analyze_with_context("insert1", 0)  # type: ignore[reportPrivateUsage]
        assert analysis.file_type == _FileType.INSERT
        assert analysis.is_new_chapter is False


class TestSequentialDetection:
    """Tests pour la logique séquentielle detect_chapters()."""

    def test_sequential_chapters(self):
        """Trois chapitres consécutifs → 3 ChapterInfo."""
        htmls = [
            make_epub_html("chapter1.html"),
            make_epub_html("chapter2.html"),
            make_epub_html("chapter3.html"),
        ]
        detector = SequentialChapterDetector(htmls)
        groups = list(detector.detect_chapters())

        assert len(groups) == 3
        for i, group in enumerate(groups):
            assert group.index == i

    def test_subpart_appended_to_chapter(self):
        """chapter1 + chapter11 → 1 chapitre avec 2 fichiers (subpart)."""
        htmls = [
            make_epub_html("chapter1.html"),
            make_epub_html("chapter11.html"),
        ]
        detector = SequentialChapterDetector(htmls)
        groups = list(detector.detect_chapters())

        assert len(groups) == 1
        assert len(groups[0].files) == 2

    def test_skip_file_excluded(self):
        """Les fichiers SKIP ne sont pas inclus dans les groupes."""
        htmls = [
            make_epub_html("cover.html"),
            make_epub_html("chapter1.html"),
            make_epub_html("toc.html"),
            make_epub_html("chapter2.html"),
        ]
        detector = SequentialChapterDetector(htmls)
        groups = list(detector.detect_chapters())

        assert len(groups) == 2

    def test_chapter_without_number_is_new_chapter(self):
        """Un chapitre sans numéro est traité comme nouveau chapitre."""
        htmls = [
            make_epub_html("prologue.html"),
            make_epub_html("chapter1.html"),
        ]
        detector = SequentialChapterDetector(htmls)
        groups = list(detector.detect_chapters())

        assert len(groups) == 2

    def test_chapter_groups_have_files(self):
        """Chaque ChapterInfo a au moins un fichier HTML."""
        htmls = [
            make_epub_html("chapter1.html"),
            make_epub_html("chapter2.html"),
        ]
        detector = SequentialChapterDetector(htmls)
        groups = list(detector.detect_chapters())

        for group in groups:
            assert len(group.files) >= 1

    def test_multi_file_chapter(self):
        """chapter1 + insert1 → 1 chapitre avec 2 fichiers."""
        htmls = [
            make_epub_html("chapter1.html"),
            make_epub_html("insert1.html"),
        ]
        detector = SequentialChapterDetector(htmls)
        groups = list(detector.detect_chapters())

        assert len(groups) == 1
        assert len(groups[0].files) == 2

    def test_chapter_names_generated(self):
        """Les noms de chapitres sont générés correctement."""
        htmls = [
            make_epub_html("chapter1.html"),
            make_epub_html("chapter2.html"),
        ]
        detector = SequentialChapterDetector(htmls)
        groups = list(detector.detect_chapters())

        for group in groups:
            assert isinstance(group.name, str)
            assert len(group.name) > 0

    def test_empty_spine_yields_nothing(self):
        """Spine vide ne yield aucun groupe."""
        detector = SequentialChapterDetector([])
        groups = list(detector.detect_chapters())
        assert len(groups) == 0


class TestChapterDetectorIntegration:
    """Tests d'intégration sur Le Petit Prince."""

    def test_detect_chapters_petit_prince(self, all_chapters: list[ChapterChunk]):
        """Le Petit Prince contient des chapitres avec contenu textuel."""
        assert len(all_chapters) > 0
        # Le Petit Prince a 27 chapitres numérotés + quelques pages de texte
        assert len(all_chapters) >= 20
        assert len(all_chapters) <= 44  # Maximum = nombre de fichiers HTML

    def test_all_chapter_groups_have_files(self, all_chapters: list[ChapterChunk]):
        """Chaque chapitre détecté a au moins un fichier HTML."""
        for chapter in all_chapters:
            assert len(chapter.files) >= 1

    def test_chapter_indices_monotonic(self, all_chapters: list[ChapterChunk]):
        """Les indices de chapitres sont strictement croissants.

        Ils ne sont pas forcément contigus (les chapitres image-only sont
        filtrés par get_all_chapters_by_spine mais incrémentent quand même
        l'index dans le détecteur).
        """
        for i in range(1, len(all_chapters)):
            assert all_chapters[i].index > all_chapters[i - 1].index

    def test_chapters_have_non_empty_names(self, all_chapters: list[ChapterChunk]):
        """Chaque chapitre a un nom non vide."""
        for chapter in all_chapters:
            assert isinstance(chapter.name, str)
            assert len(chapter.name) > 0
