"""
Tests unitaires pour la classe Segmentator.

Ces tests vérifient le comportement de segmentation du contenu
en chunks avec gestion du chevauchement (overlap).
"""

from unittest.mock import Mock

from ebook_translator.segmentation import Chunk, Segmentator


class TestSegmentator:
    """Tests pour la classe Segmentator."""

    def test_count_tokens(self):
        """Vérifie le comptage de tokens."""
        segmentator = Segmentator(
            epub_htmls=[],
            max_tokens=100,
        )

        # Texte simple
        count = segmentator.count_tokens("Hello world")
        assert count > 0
        assert isinstance(count, int)

    def test_count_tokens_empty_string(self):
        """Vérifie que le comptage d'une string vide fonctionne."""
        segmentator = Segmentator(epub_htmls=[], max_tokens=100)

        count = segmentator.count_tokens("")
        assert count == 0

    def test_overlap_ratio_calculation(self):
        """Vérifie le calcul du budget de tokens pour le chevauchement."""
        segmentator = Segmentator(
            epub_htmls=[],
            max_tokens=1000,
            overlap_ratio=0.15,
        )

        overlap_tokens = segmentator._calculate_overlap_tokens()
        assert overlap_tokens == 150  # 15% de 1000

    def test_segmentator_repr(self):
        """Vérifie la représentation pour le debug."""
        mock_htmls = [Mock(), Mock(), Mock()]
        segmentator = Segmentator(
            epub_htmls=mock_htmls,
            max_tokens=2000,
            overlap_ratio=0.2,
        )

        repr_str = repr(segmentator)

        assert "Segmentator" in repr_str
        assert "pages=3" in repr_str
        assert "max_tokens=2000" in repr_str
        assert "overlap=20%" in repr_str

    def test_chunk_index_increments(self):
        """Vérifie que les index de chunks s'incrémentent correctement."""
        # Cette fonctionnalité nécessiterait un mock complet de get_files()
        # et de epub_htmls, ce qui est complexe. Test d'intégration recommandé.
        pass

    def test_create_new_chunk(self):
        """Vérifie la création d'un nouveau chunk vide."""
        segmentator = Segmentator(epub_htmls=[], max_tokens=100)

        chunk = segmentator._create_new_chunk(index=5)

        assert isinstance(chunk, Chunk)
        assert chunk.index == 5
        assert len(chunk.body) == 0
        assert len(chunk.head) == 0
        assert len(chunk.tail) == 0

    def test_fill_head_from_previous(self):
        """Vérifie le remplissage du head depuis le chunk précédent."""
        segmentator = Segmentator(epub_htmls=[], max_tokens=1000, overlap_ratio=0.5)

        # Chunk précédent avec du body
        prev_chunk = Chunk(index=0)
        tag1, tag2, tag3 = Mock(), Mock(), Mock()
        prev_chunk.body = {
            tag1: "Text 1",  # ~2 tokens
            tag2: "Text 2",  # ~2 tokens
            tag3: "Text 3",  # ~2 tokens
        }

        # Nouveau chunk
        current_chunk = Chunk(index=1)

        # Remplir le head
        segmentator._fill_head_from_previous(prev_chunk, current_chunk)

        # Le head devrait contenir du contexte
        assert len(current_chunk.head) > 0
        # L'ordre devrait être préservé (text1, text2, text3)
        assert current_chunk.head[0] == "Text 1"
        # Tous les textes devraient être présents (budget=500, chaque text~2 tokens)
        assert len(current_chunk.head) == 3
