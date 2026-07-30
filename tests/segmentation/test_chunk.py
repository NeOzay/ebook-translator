"""
Tests unitaires et d'intégration pour la classe Chunk.

Tests unitaires : vérifient la logique interne (str, repr, prepare_for_prompt)
  sans dépendances réelles (mocks simples comme clés de dictionnaire).

Tests d'intégration : utilisent un chunk issu du vrai EPUB (fixture `chunk`)
  pour vérifier fetch_body, fetch_all, calculate_scope, calculate_hash.
"""

from unittest.mock import Mock

from ebook_translator.htmlpage import HtmlPage, TagKey
from ebook_translator.segmentation import Chunk
from tests.conftest import make_TagKey_mock


class TestChunkStr:
    """Tests pour __str__ et prepare_for_prompt."""

    def test_str_body_only(self):
        """Format LLM d'un chunk sans head ni tail."""
        chunk = Chunk(index=0)
        chunk.body = {Mock(): "Text 1", Mock(): "Text 2"}

        result = str(chunk)

        assert "<0/>Text 1" in result
        assert "<1/>Text 2" in result

    def test_str_with_head_and_tail(self):
        """Format LLM d'un chunk avec contexte head et tail."""
        chunk = Chunk(index=0)
        chunk.head = {Mock(): "Context head"}
        chunk.body = {Mock(): "Text 1", Mock(): "Text 2"}
        chunk.tail = {Mock(): "Context tail"}

        result = str(chunk)

        assert "Context head" in result
        assert "<0/>Text 1" in result
        assert "<1/>Text 2" in result
        assert "Context tail" in result

    def test_str_empty_head_tail_not_shown(self):
        """Head et tail vides n'apparaissent pas dans le format."""
        chunk = Chunk(index=0)
        chunk.body = {Mock(): "Only text"}

        result = str(chunk)

        assert "<0/>Only text" in result
        # Pas de section vide superflue
        assert result.strip() == "<0/>Only text"

    def test_prepare_for_prompt_selective(self):
        """prepare_for_prompt numérote seulement les indices spécifiés."""
        chunk = Chunk(index=0)
        chunk.body = {
            Mock(): "First line",
            Mock(): "Second line",
            Mock(): "Third line",
        }

        result = chunk.prepare_for_prompt([0, 2])

        assert "<0/>First line" in result
        assert "Second line" in result
        assert "<1/>Second line" not in result  # Pas numéroté
        assert "<2/>Third line" in result

    def test_prepare_for_prompt_includes_head_tail(self):
        """prepare_for_prompt inclut head et tail comme contexte."""
        chunk = Chunk(index=0)
        chunk.head = {Mock(): "Head context"}
        chunk.body = {Mock(): "Line 0", Mock(): "Line 1"}
        chunk.tail = {Mock(): "Tail context"}

        result = chunk.prepare_for_prompt([1])

        assert "Head context" in result
        assert "Line 0" in result  # Pas numéroté, mais présent
        assert "<0/>Line 0" not in result
        assert "<1/>Line 1" in result
        assert "Tail context" in result

    def test_prepare_for_prompt_empty_indices(self):
        """Avec indices vides, aucune ligne n'est numérotée."""
        chunk = Chunk(index=0)
        chunk.body = {Mock(): "Line 0", Mock(): "Line 1"}

        result = chunk.prepare_for_prompt([])

        assert "<0/>" not in result
        assert "Line 0" in result
        assert "Line 1" in result


class TestChunkRepr:
    """Tests pour __repr__."""

    def test_repr_shows_counts(self):
        """repr affiche l'index et les tailles de head/body/tail."""
        chunk = Chunk(index=5)
        chunk.head = {Mock(): "h1", Mock(): "h2"}
        chunk.body = {Mock(): "t1", Mock(): "t2", Mock(): "t3"}
        chunk.tail = {Mock(): "t1"}

        repr_str = repr(chunk)

        assert "Chunk" in repr_str
        assert "index=5" in repr_str
        assert "body_items=3" in repr_str
        assert "head_items=2" in repr_str
        assert "tail_items=1" in repr_str


class TestChunkSizes:
    """Tests pour get_body_size, get_head_size, get_tail_size."""

    def test_sizes_empty_chunk(self):
        """Chunk vide retourne 0 pour toutes les tailles."""
        chunk = Chunk(index=0)
        assert chunk.get_body_size() == 0
        assert chunk.get_head_size() == 0
        assert chunk.get_tail_size() == 0

    def test_sizes_with_content(self):
        """Tailles cohérentes avec le contenu réel."""
        chunk = Chunk(index=0)
        chunk.head = {Mock(): "h1"}
        chunk.body = {Mock(): "b1", Mock(): "b2"}
        chunk.tail = {Mock(): "t1", Mock(): "t2", Mock(): "t3"}

        assert chunk.get_head_size() == 1
        assert chunk.get_body_size() == 2
        assert chunk.get_tail_size() == 3


class TestChunkHash:
    """Tests pour calculate_chunk_hash."""

    def test_same_content_same_hash(self):
        """Deux chunks avec le même body ont le même hash."""
        key1 = Mock()
        key2 = Mock()

        chunk1 = Chunk(index=0)
        chunk1.body = {key1: "Same text"}
        chunk2 = Chunk(index=0)
        chunk2.body = {key2: "Same text"}

        assert chunk1.calculate_chunk_hash() == chunk2.calculate_chunk_hash()

    def test_different_content_different_hash(self):
        """Deux chunks avec des bodies différents ont des hashs différents."""
        chunk1 = Chunk(index=0)
        chunk1.body = {Mock(): "Text A"}
        chunk2 = Chunk(index=0)
        chunk2.body = {Mock(): "Text B"}

        assert chunk1.calculate_chunk_hash() != chunk2.calculate_chunk_hash()

    def test_empty_body_hash_stable(self):
        """Hash d'un chunk vide est stable (même résultat à chaque appel)."""
        chunk = Chunk(index=0)
        assert chunk.calculate_chunk_hash() == chunk.calculate_chunk_hash()


class TestChunkFetch:
    """Tests pour fetch_body et fetch_all avec TagKey réels."""

    def test_fetch_body_yields_page_tagkey_text(self):
        """fetch_body() yield des tuples (page, TagKey, str)."""
        chunk = Chunk(index=0)
        tag1 = make_TagKey_mock(0)
        tag2 = make_TagKey_mock(1)
        chunk.body = {tag1: "Text 1", tag2: "Text 2"}

        items = list(chunk.fetch_body())

        assert len(items) == 2
        assert items[0] == (tag1.page, tag1, "Text 1")
        assert items[1] == (tag2.page, tag2, "Text 2")

    def test_fetch_all_includes_head_body_tail(self):
        """fetch_all() inclut les fragments de head, body et tail."""
        chunk = Chunk(index=0)
        head_tag = make_TagKey_mock(10)
        body_tag = make_TagKey_mock(20)
        tail_tag = make_TagKey_mock(30)

        chunk.head = {head_tag: "Head text"}
        chunk.body = {body_tag: "Body text"}
        chunk.tail = {tail_tag: "Tail text"}

        items = list(chunk.fetch_all())

        assert len(items) == 3
        texts = [text for _, _, text in items]
        assert "Head text" in texts
        assert "Body text" in texts
        assert "Tail text" in texts

    def test_fetch_body_empty_yields_nothing(self):
        """fetch_body() sur un chunk sans body ne yield rien."""
        chunk = Chunk(index=0)
        assert list(chunk.fetch_body()) == []


class TestChunkIntegration:
    """Tests d'intégration utilisant un chunk issu du vrai EPUB."""

    def test_real_chunk_has_body(self, chunk: Chunk):
        """Un chunk réel a un body non vide."""
        assert chunk.get_body_size() > 0

    def test_real_chunk_str_format(self, chunk: Chunk):
        """Le format str d'un chunk réel contient la balise LLM <0/>."""
        result = str(chunk)
        assert "<0/>" in result

    def test_real_chunk_fetch_body_types(self, chunk: Chunk):
        """fetch_body() sur chunk réel yield les bons types."""
        items = list(chunk.fetch_body())

        assert len(items) > 0
        for page, tag_key, text in items:
            assert isinstance(page, HtmlPage)
            assert isinstance(tag_key, TagKey)
            assert isinstance(text, str)
            assert len(text) > 0

    def test_real_chunk_calculate_scope(self, chunk: Chunk):
        """calculate_scope() retourne une liste de tuples (str, int)."""
        scope = chunk.calculate_scope()

        assert isinstance(scope, list)
        assert len(scope) >= 1
        for file_name, line_number in scope:
            assert isinstance(file_name, str)
            assert isinstance(line_number, int)

    def test_real_chunk_scope_cached(self, chunk: Chunk):
        """La propriété scope est mise en cache (accès répété → même objet)."""
        scope1 = chunk.scope
        scope2 = chunk.scope
        assert scope1 is scope2
