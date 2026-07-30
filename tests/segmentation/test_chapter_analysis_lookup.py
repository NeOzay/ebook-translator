"""Tests de `Chapters.get_literary_analysis` sur l'API `analysis_lookup`.

`Chapters` ne lit plus le cache de Phase 0 lui-même : il résout le chapitre
du chunk, puis délègue à un callable injecté (typiquement
`LiteraryAnalysisPhase.latest_analysis_for`). Ces tests couvrent les trois
issues : pas de lookup, chapitre introuvable, délégation nominale.
"""

from __future__ import annotations

import pytest

import tests.conftest as root_conftest
from ebook_translator.segmentation import Chunk
from ebook_translator.segmentation.chapter import Chapters
from template.phase.analyze_chapter_layered_models import (
    AnalyseChapter,
    CoucheNarrative,
    NoyauStable,
)


def _analyse(chapitre: str) -> AnalyseChapter:
    """Fiche minimale valide, identifiable par son champ `chapitre`."""
    return AnalyseChapter(
        chapitre=chapitre,
        noyau_stable=NoyauStable(
            genre_affine="conte philosophique",
            registre="soutenu",
            style_auctorial="dépouillé",
            tonalite_generale="mélancolique",
            pistes_traduction=["préserver la simplicité du lexique"],
        ),
        couche_narrative=CoucheNarrative(
            resume_narratif="Un aviateur rencontre un enfant.",
            arcs_en_cours=[],
            tensions=[],
            themes_emergents=[],
            references_culturelles_rencontrees=[],
        ),
    )


@pytest.fixture
def a_chunk() -> Chunk:
    """Premier chunk du vrai EPUB de test."""
    return root_conftest.a_chunk


class TestGetLiteraryAnalysis:
    def test_no_lookup_returns_none(self, a_chunk: Chunk) -> None:
        """Phase 0 absente du pipeline → aucun contexte littéraire."""
        chapters = Chapters(root_conftest.source_book)

        assert chapters.get_literary_analysis(a_chunk) is None

    def test_delegates_with_chapter_name(self, a_chunk: Chunk) -> None:
        """Le lookup est appelé avec le nom du chapitre résolu, pas le chunk."""
        seen: list[str] = []

        def lookup(chapter_name: str) -> AnalyseChapter | None:
            seen.append(chapter_name)
            return _analyse(chapter_name)

        chapters = Chapters(root_conftest.source_book, lookup)
        expected = chapters.get_chapter_for_chunk(a_chunk)
        assert expected is not None, "le chunk de test doit appartenir à un chapitre"

        result = chapters.get_literary_analysis(a_chunk)

        assert seen == [expected.name]
        assert result is not None
        assert result.chapitre == expected.name

    def test_lookup_miss_returns_none(self, a_chunk: Chunk) -> None:
        """Phase 0 présente mais sans fiche pour ce chapitre."""
        chapters = Chapters(root_conftest.source_book, lambda _: None)

        assert chapters.get_literary_analysis(a_chunk) is None

    def test_unknown_chunk_skips_lookup(self) -> None:
        """Chunk hors des chapitres détectés → le lookup n'est pas appelé."""
        calls: list[str] = []

        def lookup(chapter_name: str) -> AnalyseChapter | None:
            calls.append(chapter_name)
            return _analyse(chapter_name)

        chapters = Chapters.from_html_items([], lookup)

        assert chapters.get_literary_analysis(root_conftest.a_chunk) is None
        assert calls == []
