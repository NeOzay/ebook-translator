import pytest

from ebook_translator.htmlpage import TagKey
from ebook_translator.segmentation import Chunk
from ebook_translator.segmentation.helper import (
    count_tokens,
    is_included_in_scope,
    turn_resource_to_chunks,
)
from tests.conftest import make_TagKey_mock


class TestCountTokens:
    """Tests pour count_tokens."""

    def test_basic_text_returns_positive_count(self):
        """Un texte non vide retourne un nombre positif de tokens."""
        count = count_tokens("hello world", "o200k_base")
        assert count > 0
        assert isinstance(count, int)

    def test_empty_string_returns_zero(self):
        """Une string vide retourne 0 tokens."""
        assert count_tokens("", "o200k_base") == 0

    def test_longer_text_has_more_tokens(self):
        """Un texte plus long a plus de tokens."""
        short = count_tokens("hi", "o200k_base")
        long = count_tokens("hello world how are you today", "o200k_base")
        assert long > short

    def test_french_text(self):
        """Texte en français compte des tokens correctement."""
        count = count_tokens("Le petit prince habitait une planète", "o200k_base")
        assert count > 0


class TestTurnResourceToChunks:
    """Tests pour turn_resource_to_chunks."""

    def _make_items(self, texts: list[str]) -> list[tuple[TagKey, str]]:
        """Crée des (TagKey, texte) à partir d'une liste de textes."""
        return [(make_TagKey_mock(i), text) for i, text in enumerate(texts)]

    def test_basic_chunking(self):
        """Des fragments courts rentrent dans un seul chunk."""
        items = self._make_items(["a", "b", "c"])
        chunks = list(turn_resource_to_chunks(iter(items), max_tokens=500))

        assert len(chunks) >= 1
        # Tous les textes doivent être dans les bodies
        all_texts: set[str] = set()
        for chunk in chunks:
            all_texts.update(chunk.body.values())
        assert all_texts == {"a", "b", "c"}

    def test_token_limit_respected(self):
        """Aucun chunk body ne dépasse max_tokens."""
        # Textes longs pour forcer plusieurs chunks
        long_texts = [
            "Le petit prince habitait la planète B 612, très petite planète." * 3
        ] * 20
        items = self._make_items(long_texts)
        chunks = list(turn_resource_to_chunks(iter(items), max_tokens=50))

        for chunk in chunks:
            # Chaque fragment individuellement doit être <= max_tokens
            for text in chunk.body.values():
                assert count_tokens(text, "o200k_base") <= 50 * 3

    def test_first_chunk_no_head(self):
        """Le premier chunk n'a pas de head (pas de contexte précédent)."""
        many_texts = ["word " * 10] * 30
        items = self._make_items(many_texts)
        chunks = list(
            turn_resource_to_chunks(iter(items), max_tokens=20, overlap_ratio=0.3)
        )

        assert len(chunks) >= 2
        assert chunks[0].get_head_size() == 0

    def test_subsequent_chunks_have_head(self):
        """Les chunks suivants ont un head (overlap du chunk précédent).

        Le budget overlap doit être > coût d'un item pour qu'au moins un item
        soit inséré dans le head. Ici max_tokens=10, overlap_ratio=0.5 →
        budget=5 tokens. Chaque "word " ≈ 1 token → 5 items entrent dans le head.
        """
        # "word " ≈ 1 token, max_tokens=10 → ~10 items par chunk
        many_texts = ["word "] * 50
        items = self._make_items(many_texts)
        chunks = list(
            turn_resource_to_chunks(iter(items), max_tokens=10, overlap_ratio=0.5)
        )

        assert len(chunks) >= 2
        assert chunks[1].get_head_size() > 0

    def _overlapping_chunks(self, balance: float) -> list[Chunk]:
        """Chunks à chevauchement, à `head_tail_balance` près.

        "word " ≈ 1 token, max_tokens=10 → ~10 items par chunk, et un budget de
        chevauchement de 10 tokens (`max_tokens * overlap_ratio * 2`) que
        `balance` répartit entre head et tail.
        """
        items = self._make_items(["word "] * 50)
        return list(
            turn_resource_to_chunks(
                iter(items),
                max_tokens=10,
                overlap_ratio=0.5,
                head_tail_balance=balance,
            )
        )

    @pytest.mark.parametrize("balance", [-0.1, 1.1])
    def test_balance_out_of_range_is_rejected(self, balance: float) -> None:
        """Hors de [0, 1], la répartition n'a pas de sens."""
        with pytest.raises(
            ValueError, match="head_tail_balance must be between 0 and 1"
        ):
            _ = list(
                turn_resource_to_chunks(
                    iter(self._make_items(["word "] * 5)),
                    max_tokens=10,
                    head_tail_balance=balance,
                )
            )

    def test_higher_balance_gives_a_bigger_head(self) -> None:
        """`balance` est la part du budget de chevauchement allouée au head."""
        head_light = self._overlapping_chunks(0.2)[1].get_head_size()
        head_heavy = self._overlapping_chunks(0.8)[1].get_head_size()

        assert head_heavy > head_light

    def test_balance_one_puts_everything_in_the_head(self) -> None:
        """Tout au head : les chunks n'ont plus de tail du tout."""
        chunks = self._overlapping_chunks(1.0)

        assert chunks[1].get_head_size() > 0
        assert all(chunk.get_tail_size() == 0 for chunk in chunks)

    def test_balance_zero_puts_everything_in_the_tail(self) -> None:
        """Tout au tail : plus aucun head, le contexte passe par l'aval."""
        chunks = self._overlapping_chunks(0.0)

        assert all(chunk.get_head_size() == 0 for chunk in chunks)
        assert any(chunk.get_tail_size() > 0 for chunk in chunks)

    def test_chunks_have_sequential_indices(self):
        """Les indices des chunks sont 0, 1, 2, ..."""
        many_texts = ["word " * 10] * 30
        items = self._make_items(many_texts)
        chunks = list(turn_resource_to_chunks(iter(items), max_tokens=20))

        for expected, chunk in enumerate(chunks):
            assert chunk.index == expected

    def test_empty_input_yields_one_empty_chunk(self):
        """Input vide yield un seul chunk vide."""
        chunks = list(turn_resource_to_chunks(iter([]), max_tokens=100))

        assert len(chunks) == 1
        assert chunks[0].get_body_size() == 0

    def test_returns_chunk_instances(self):
        """Chaque élément yielded est une instance de Chunk."""
        items = self._make_items(["hello", "world"])
        chunks = list(turn_resource_to_chunks(iter(items), max_tokens=500))

        for chunk in chunks:
            assert isinstance(chunk, Chunk)


class TestIsIncludedInScope:
    """Tests pour is_included_in_scope."""

    def test_empty_in_scope_returns_false(self) -> None:
        """Vérifie que in_scope vide retourne False (moins de 2 éléments)."""
        in_scope: list[tuple[str, int]] = []
        out_scope: list[tuple[str, int]] = [("file.html", 10)]
        assert is_included_in_scope(in_scope, out_scope) is False

    def test_empty_out_scope_returns_false(self) -> None:
        """Vérifie que out_scope vide retourne False (moins de 2 éléments)."""
        in_scope: list[tuple[str, int]] = [("file.html", 5)]
        out_scope: list[tuple[str, int]] = []
        assert is_included_in_scope(in_scope, out_scope) is False

    def test_both_scopes_empty_returns_false(self) -> None:
        """Vérifie que deux scopes vides retournent False (moins de 2 éléments)."""
        in_scope: list[tuple[str, int]] = []
        out_scope: list[tuple[str, int]] = []
        assert is_included_in_scope(in_scope, out_scope) is False

    def test_single_element_included(self) -> None:
        """in_scope avec un seul élément inclus retourne False, car une seule borne."""
        in_scope: list[tuple[str, int]] = [("file.html", 10)]
        out_scope: list[tuple[str, int]] = [("file.html", 5), ("file.html", 15)]
        assert is_included_in_scope(in_scope, out_scope) is False

    def test_in_scope_not_exhausted_returns_false(self) -> None:
        """Vérifie que si in_scope reste, retourne False."""
        in_scope: list[tuple[str, int]] = [
            ("file.html", 5),
            ("file.html", 10),
        ]
        out_scope: list[tuple[str, int]] = [("file.html", 3)]
        assert is_included_in_scope(in_scope, out_scope) is False

    def test_out_scope_with_minus_one_line_number(self) -> None:
        """Vérifie que line_number=-1 accepte tous les numéros de ligne suivants."""
        in_scope: list[tuple[str, int]] = [
            ("file.html", 5),
            ("file.html", 999),
        ]
        out_scope: list[tuple[str, int]] = [("file.html", -1)]
        assert is_included_in_scope(in_scope, out_scope) is False

    def test_multiple_elements_all_included(self) -> None:
        """Vérifie que plusieurs éléments inclus retournent True.

        in_scope[0] ("file.html", 5) >= out_scope[0] ("file.html", 3) ✓ (borne inf)
        in_scope[1] ("file.html", 10) <= out_scope[1] ("file.html", 12) ✓ (borne sup)
        Tous les éléments de in_scope sont consommés, retourne True.
        """
        in_scope: list[tuple[str, int]] = [
            ("file.html", 5),
            ("file.html", 10),
        ]
        out_scope: list[tuple[str, int]] = [
            ("file.html", 3),
            ("file.html", 12),
        ]
        assert is_included_in_scope(in_scope, out_scope) is True

    def test_multiple_elements_partial_included_returns_false(self) -> None:
        """Vérifie que si un élément n'est pas inclus, retourne False.

        in_scope[0] ("file.html", 5) >= out_scope[0] ("file.html", 3) ✓ (borne inf)
        in_scope[1] ("file.html", 15) > out_scope[1] ("file.html", 12) ✗ (borne sup)
        Le deuxième élément dépasse la borne supérieure, retourne False.
        """
        in_scope: list[tuple[str, int]] = [
            ("file.html", 5),
            ("file.html", 15),
        ]
        out_scope: list[tuple[str, int]] = [
            ("file.html", 3),
            ("file.html", 12),
        ]
        assert is_included_in_scope(in_scope, out_scope) is False

    def test_multiple_files_included(self) -> None:
        """Vérifie que plusieurs fichiers inclus retournent True.

        in_scope[0] ("chapter1.html", 5) >= out_scope[0] ("chapter1.html", 3) ✓
        in_scope[1] ("chapter2.html", 10) <= out_scope[1] ("chapter2.html", 15) ✓
        Tous les éléments sont inclus, retourne True.
        """
        in_scope: list[tuple[str, int]] = [
            ("chapter1.html", 5),
            ("chapter2.html", 10),
        ]
        out_scope: list[tuple[str, int]] = [
            ("chapter1.html", 3),
            ("chapter2.html", 15),
        ]
        assert is_included_in_scope(in_scope, out_scope) is True

    def test_multiple_files_partial_included_returns_false(self) -> None:
        """Vérifie que si un fichier diffère, retourne False.

        in_scope[0] ("chapter1.html", 5) >= out_scope[0] ("chapter1.html", 3) ✓
        in_scope[1] ("chapter3.html", 10) != out_scope[1] ("chapter2.html", 12) ✗
        Fichier différent (chapter3 vs chapter2), retourne False.
        """
        in_scope: list[tuple[str, int]] = [
            ("chapter1.html", 5),
            ("chapter3.html", 10),  # Fichier différent
        ]
        out_scope: list[tuple[str, int]] = [
            ("chapter1.html", 3),
            ("chapter2.html", 12),
        ]
        assert is_included_in_scope(in_scope, out_scope) is False

    def test_out_scope_minus_one_then_bounded(self) -> None:
        """Vérifie la transition entre line_number=-1 et limites normales.

        in_scope[0] ("file.html", 5) est inclus dans out_scope[0] ("file.html", -1).
        in_scope[1] ("file2.html", 15) n'est PAS inclus dans out_scope[1] ("file2.html", 12)
        car 15 > 12. Donc retourne False.
        """
        in_scope: list[tuple[str, int]] = [
            ("file.html", 5),
            ("file2.html", 15),
        ]
        out_scope: list[tuple[str, int]] = [("file.html", -1), ("file2.html", 12)]
        assert is_included_in_scope(in_scope, out_scope) is False

    def test_complex_scenario_multiple_files_and_ranges(self) -> None:
        """Vérifie un scénario complexe avec plusieurs fichiers et plages.

        in_scope[0] ("chapter1.html", 5) >= out_scope[0] ("chapter1.html", 0) ✓ (borne inf)
        in_scope[1] ("chapter2.html", -1) correspond à out_scope[1] ("chapter2.html", -1) ✓
        in_scope[2] ("chapter3.html", 8) avec out_scope[2] ("chapter3.html", -1) ✓ (-1 accepte tout)
        Tous les éléments sont consommés, retourne True.
        """
        in_scope: list[tuple[str, int]] = [
            ("chapter1.html", 5),
            ("chapter2.html", -1),
            ("chapter3.html", 8),
        ]
        out_scope: list[tuple[str, int]] = [
            ("chapter1.html", 0),
            ("chapter2.html", -1),
            ("chapter3.html", -1),
        ]
        assert is_included_in_scope(in_scope, out_scope) is True

    def test_complex_scenario_multiple_files_and_ranges2(self) -> None:
        """Vérifie un scénario complexe avec plusieurs fichiers et plages.

        in_scope a 4 éléments, out_scope en a 3.
        Retourne False car len(in_scope) > len(out_scope) (condition ligne 181).
        """
        in_scope: list[tuple[str, int]] = [
            ("chapter1.html", 5),
            ("chapter1.html", -1),
            ("chapter3.html", -1),
            ("chapter4.html", 10),
        ]
        out_scope: list[tuple[str, int]] = [
            ("chapter1.html", 0),
            ("chapter2.html", -1),
            ("chapter3.html", -1),
        ]
        assert is_included_in_scope(in_scope, out_scope) is False

    def test_sequential_files_with_boundary_conditions(self) -> None:
        """Vérifie les conditions limites avec fichiers séquentiels.

        in_scope[0] ("file1.html", 0) >= out_scope[0] ("file1.html", 0) ✓
        in_scope[1] ("file2.html", -1) avec out_scope[1] ("file2.html", -1) ✓
        in_scope[2] ("file3.html", 1) <= out_scope[2] ("file3.html", 1) ✓
        Scopes identiques, retourne True.
        """
        in_scope: list[tuple[str, int]] = [
            ("file1.html", 0),
            ("file2.html", -1),
            ("file3.html", 1),
        ]
        out_scope: list[tuple[str, int]] = [
            ("file1.html", 0),
            ("file2.html", -1),
            ("file3.html", 1),
        ]
        assert is_included_in_scope(in_scope, out_scope) is True

    def test_skip_intermediate_file(self) -> None:
        """Vérifie qu'on peut sauter un fichier intermédiaire dans out_scope.

        in_scope[0] ("file1.html", 0) >= out_scope[0] ("file1.html", 0) ✓
        in_scope[1] ("file3.html", 1) != out_scope[1] ("file2.html", -1), fichier différent
        On continue dans out_scope, out_scope[2] ("file3.html", 1)
        in_scope[1] ("file3.html", 1) <= out_scope[2] ("file3.html", 1) ✓
        Tous consommés, retourne True.
        """
        in_scope: list[tuple[str, int]] = [
            ("file1.html", 0),
            ("file3.html", 1),
        ]
        out_scope: list[tuple[str, int]] = [
            ("file1.html", 0),
            ("file2.html", -1),
            ("file3.html", 1),
        ]
        assert is_included_in_scope(in_scope, out_scope) is True

    def test_skip_first_file_in_out_scope(self) -> None:
        """Vérifie qu'on peut sauter le premier fichier de out_scope.

        in_scope[0] ("b.html", 50) != out_scope[0] ("a.html", 0), fichier différent
        On continue dans out_scope, out_scope[1] ("b.html", -1)
        in_scope[0] ("b.html", 50) avec out_scope[1] ("b.html", -1) ✓ (borne inf, -1 accepte tout)
        in_scope[1] ("c.html", 10) <= out_scope[2] ("c.html", 20) ✓ (borne sup)
        Tous consommés, retourne True.
        """
        in_scope: list[tuple[str, int]] = [
            ("b.html", 50),
            ("c.html", 10),
        ]
        out_scope: list[tuple[str, int]] = [
            ("a.html", 0),
            ("b.html", -1),
            ("c.html", 20),
        ]
        assert is_included_in_scope(in_scope, out_scope) is True

    def test_multiple_lines_same_file_with_minus_one(self) -> None:
        """Vérifie que plusieurs lignes du même fichier fonctionnent avec -1.

        in_scope[0] ("b.html", 10) != out_scope[0] ("a.html", 0), fichier différent
        On continue dans out_scope, out_scope[1] ("b.html", -1)
        in_scope[0] ("b.html", 10) avec out_scope[1] ("b.html", -1) ✓ (borne inf, -1 accepte tout)
        in_scope[1] ("b.html", 50) avec out_scope[1] ("b.html", -1) ✓ (-1 accepte tout)
        Tous consommés, retourne True.
        """
        in_scope: list[tuple[str, int]] = [
            ("b.html", 10),
            ("b.html", 50),
        ]
        out_scope: list[tuple[str, int]] = [
            ("a.html", 0),
            ("b.html", -1),
            ("c.html", 20),
        ]
        assert is_included_in_scope(in_scope, out_scope) is True

    def test_skip_multiple_files_in_out_scope(self) -> None:
        """Vérifie qu'on peut sauter plusieurs fichiers au début de out_scope.

        Itération 1: out_scope[0] ("a.html", 0), in_file="c.html" != "a.html", break
        Itération 2: out_scope[1] ("b.html", -1), in_file="c.html" != "b.html", break
        Itération 3: out_scope[2] ("c.html", 5), is_first_match=True
          - in_scope[0] ("c.html", 10) >= 5 ✓ (borne inf), avance à in_scope[1]
        Itération 4: out_scope[3] ("c.html", 25), is_first_match=False
          - in_scope[1] ("c.html", 20) <= 25 ✓ (borne sup), avance à (None, None)
        Tous consommés, retourne True.
        """
        in_scope: list[tuple[str, int]] = [
            ("c.html", 10),
            ("c.html", 20),
        ]
        out_scope: list[tuple[str, int]] = [
            ("a.html", 0),
            ("b.html", -1),
            ("c.html", 20),
        ]
        assert is_included_in_scope(in_scope, out_scope) is True

    def test_bug_first_match_reset_with_skip(self) -> None:
        """Vérifie que is_first_match n'est pas reset prématurément (bug critique).

        Test de régression pour le bug où is_first_match était reset même si
        le while n'était pas exécuté (fichier différent).

        Itération 1: out_scope[0] ("a.html", 0), in_file="b.html" != "a.html"
          → while pas exécuté, is_first_match DOIT rester True
        Itération 2: out_scope[1] ("b.html", 100), in_file="b.html" == "b.html"
          → while exécuté, is_first_match=True → validation borne inf
          → 50 < 100 → return True ✓
        """
        in_scope: list[tuple[str, int]] = [
            ("b.html", 50),
            ("c.html", 10),
        ]
        out_scope: list[tuple[str, int]] = [
            ("a.html", 0),
            ("b.html", 100),
            ("c.html", 20),
        ]
        assert is_included_in_scope(in_scope, out_scope) is True

    def test_first_match_with_wildcard_after_skip(self) -> None:
        """Vérifie que -1 au premier match accepte tout après skip.

        Test de régression pour vérifier que -1 fonctionne correctement
        comme borne inférieure (premier match) après avoir skip des fichiers.

        Itération 1: skip "a.html" (fichier différent)
        Itération 2: match "b.html", -1 comme borne inf accepte 999 ✓
        Itération 3: match "c.html", 10 <= 20 ✓ (borne sup)
        """
        in_scope: list[tuple[str, int]] = [
            ("b.html", 999),
            ("c.html", 10),
        ]
        out_scope: list[tuple[str, int]] = [
            ("a.html", 0),
            ("b.html", -1),
            ("c.html", 20),
        ]
        assert is_included_in_scope(in_scope, out_scope) is True
