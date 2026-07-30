"""Tests des `build` callables du `RETRY_REGISTRY` (Bloc B Step 1+2).

Vérifie pour chaque `ErreursType` couvert que :
- le `build` consomme un `ValidationFailure` typé + `RetryContext`,
- produit un `params_type` complet (toutes les clés requises),
- propage correctement les valeurs (target_language, indices, comptes).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ebook_translator.llm.retry_registry import RETRY_REGISTRY
from ebook_translator.validation.diagnostics import (
    ErreursType,
    FragmentDiagnostic,
    LinesMissingDiagnostic,
    PunctuationDiagnostic,
    SentenceDiagnostic,
)
from ebook_translator.validation.failure import ValidationFailure


@dataclass(frozen=True)
class _FakeSource:
    texts: dict[int, str]

    @property
    def line_indices(self) -> Iterable[int]:
        return self.texts.keys()

    def text_at(self, index: int) -> str:
        return self.texts[index]


@dataclass
class _FakeChunk:
    """Chunk minimal — `prepare_for_prompt` retourne un rendu fake déterministe."""

    rendered: dict[tuple[int, ...], str]

    def prepare_for_prompt(
        self, index_to_mark: list[int] | None = None, **_: object
    ) -> str:
        key = tuple(index_to_mark or [])
        return self.rendered.get(key, f"<rendered:{key}>")


@dataclass
class _FakeContext:
    target_language: str
    chunk: _FakeChunk
    source: _FakeSource
    current_data: dict[int, str]

    # Lus par `_build_fragments` pour choisir le mode strict/flexible.
    max_attempts: int = 2
    attempt: int = 0


# ---------- LINES_MISSING ----------


class TestBuildMissingLines:
    def _ctx(self) -> _FakeContext:
        return _FakeContext(
            target_language="fr",
            chunk=_FakeChunk(rendered={(1, 3): "<rendered missing>"}),
            source=_FakeSource(texts={0: "x", 1: "y", 2: "z", 3: "w"}),
            current_data={0: "X", 2: "Z"},
        )

    def test_produces_complete_params(self) -> None:
        entry = RETRY_REGISTRY[ErreursType.LINES_MISSING]
        failure = ValidationFailure[LinesMissingDiagnostic](
            error_type=ErreursType.LINES_MISSING,
            msg="2 manquantes",
            ctx={"missing_indices": [1, 3]},
            relevant_indices=frozenset({1, 3}),
        )
        params = entry.build(failure, self._ctx())  # type: ignore[arg-type]
        assert params["target_language"] == "fr"
        assert params["missing_indices"] == [1, 3]
        assert params["source_content"] == "<rendered missing>"
        assert "1" in params["error_message"] and "3" in params["error_message"]

    def test_error_message_truncates_long_lists(self) -> None:
        entry = RETRY_REGISTRY[ErreursType.LINES_MISSING]
        many = list(range(10))
        ctx = _FakeContext(
            target_language="fr",
            chunk=_FakeChunk(rendered={}),
            source=_FakeSource(texts={i: "" for i in many}),
            current_data={},
        )
        failure = ValidationFailure[LinesMissingDiagnostic](
            error_type=ErreursType.LINES_MISSING,
            msg="10 manquantes",
            ctx={"missing_indices": many},
            relevant_indices=frozenset(many),
        )
        params = entry.build(failure, ctx)  # type: ignore[arg-type]
        assert "+5 autres" in params["error_message"]


# ---------- FRAGMENT_COUNT_MISMATCH ----------


class TestBuildFragments:
    def test_per_line_payload(self) -> None:
        entry = RETRY_REGISTRY[ErreursType.FRAGMENT_COUNT_MISMATCH]
        ctx = _FakeContext(
            target_language="fr",
            chunk=_FakeChunk(rendered={}),
            source=_FakeSource(texts={5: "src5</>part"}),
            current_data={5: "trad5_pas_de_sep"},
        )
        failure = ValidationFailure[FragmentDiagnostic](
            error_type=ErreursType.FRAGMENT_COUNT_MISMATCH,
            msg="ligne 5: 0 sep, 1 attendu",
            ctx={"line": 5, "expected_pairs": 1, "actual_pairs": 0},
            relevant_indices=frozenset({5}),
        )
        params = entry.build(failure, ctx)  # type: ignore[arg-type]
        assert params["target_language"] == "fr"
        assert params["original_text"] == "src5</>part"
        assert params["incorrect_translation"] == "trad5_pas_de_sep"
        assert params["expected_separators"] == 1
        assert params["actual_separators"] == 0
        assert params["mode"] == "strict"


# ---------- PUNCTUATION_MISMATCH ----------


class TestBuildPunctuation:
    def test_per_line_payload(self) -> None:
        entry = RETRY_REGISTRY[ErreursType.PUNCTUATION_MISMATCH]
        ctx = _FakeContext(
            target_language="fr",
            chunk=_FakeChunk(rendered={}),
            source=_FakeSource(texts={2: "« hello »"}),
            current_data={2: "hello"},
        )
        failure = ValidationFailure[PunctuationDiagnostic](
            error_type=ErreursType.PUNCTUATION_MISMATCH,
            msg="ligne 2: 0 paire, 1 attendue",
            ctx={"line": 2, "expected_pairs": 1, "actual_pairs": 0},
            relevant_indices=frozenset({2}),
        )
        params = entry.build(failure, ctx)  # type: ignore[arg-type]
        assert params["target_language"] == "fr"
        assert params["original_text"] == "« hello »"
        assert params["incorrect_translation"] == "hello"
        assert params["expected_pairs"] == 1
        assert params["actual_pairs"] == 0


# ---------- SENTENCE_INVALID ----------


class TestBuildSentence:
    def test_aggregated_payload(self) -> None:
        entry = RETRY_REGISTRY[ErreursType.SENTENCE_INVALID]
        ctx = _FakeContext(
            target_language="fr",
            chunk=_FakeChunk(rendered={(2, 4): "<rendered sent>"}),
            source=_FakeSource(texts={2: "Phrase un. Phrase deux.", 4: "X. Y."}),
            current_data={2: "Phrase fusion", 4: "X Y"},
        )
        failure = ValidationFailure[SentenceDiagnostic](
            error_type=ErreursType.SENTENCE_INVALID,
            msg="2 lignes invalides",
            ctx={"invalid_indices": [2, 4]},
            relevant_indices=frozenset({2, 4}),
        )
        params = entry.build(failure, ctx)  # type: ignore[arg-type]
        assert params["target_language"] == "fr"
        assert params["original_text"] == "<rendered sent>"
        assert params["previous_translation"] == "<2/>Phrase fusion\n<4/>X Y"
        assert params["missing_indices"] == "<2/>, <4/>"

    def test_skips_indices_absent_from_current_data(self) -> None:
        entry = RETRY_REGISTRY[ErreursType.SENTENCE_INVALID]
        ctx = _FakeContext(
            target_language="fr",
            chunk=_FakeChunk(rendered={(2, 4): "<rendered>"}),
            source=_FakeSource(texts={2: "x", 4: "y"}),
            current_data={2: "X"},  # 4 absent
        )
        failure = ValidationFailure[SentenceDiagnostic](
            error_type=ErreursType.SENTENCE_INVALID,
            msg="invalides",
            ctx={"invalid_indices": [2, 4]},
            relevant_indices=frozenset({2, 4}),
        )
        params = entry.build(failure, ctx)  # type: ignore[arg-type]
        # Seul l'indice présent dans current_data est rendu côté traduction
        assert params["previous_translation"] == "<2/>X"
        # missing_indices liste les deux (string formatée)
        assert params["missing_indices"] == "<2/>, <4/>"
