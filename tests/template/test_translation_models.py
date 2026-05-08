"""Tests de `LineIndexedTranslation`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ebook_translator.validation.diagnostics import ErreursType
from ebook_translator.validation.failure import from_pydantic_error
from template.phase.translation_models import LineIndexedTranslation


class TestParseValid:
    def test_simple_two_lines(self):
        raw = "<0/>Bonjour\n<1/>Monde\n[=[END]=]"
        m = LineIndexedTranslation.model_validate(raw)
        assert m.lines == {0: "Bonjour", 1: "Monde"}

    def test_non_sequential_indices(self):
        raw = "<3/>x\n<7/>y\n[=[END]=]"
        m = LineIndexedTranslation.model_validate(raw)
        assert m.lines == {3: "x", 7: "y"}

    def test_trailing_whitespace_tolerated(self):
        raw = "  <0/>x\n[=[END]=]   "
        m = LineIndexedTranslation.model_validate(raw)
        assert m.lines == {0: "x"}

    def test_dict_input_passthrough(self):
        m = LineIndexedTranslation.model_validate({"lines": {0: "x", 1: "y"}})
        assert m.lines == {0: "x", 1: "y"}

    def test_fragment_separator_preserved(self):
        raw = "<0/>a</>b</>c\n[=[END]=]"
        m = LineIndexedTranslation.model_validate(raw)
        assert m.fragments_at(0) == ["a", "b", "c"]


class TestParseErrors:
    def test_missing_end_marker_emits_typed_error(self):
        raw = "<0/>x\n<1/>y"
        with pytest.raises(ValidationError) as exc_info:
            LineIndexedTranslation.model_validate(raw)

        failures = from_pydantic_error(exc_info.value)
        assert len(failures) == 1
        assert failures[0].error_type is ErreursType.MISSING_END_MARKER
        assert "detail" in failures[0].ctx

    def test_no_segment_emits_output_format_invalid(self):
        raw = "blabla aucun segment\n[=[END]=]"
        with pytest.raises(ValidationError) as exc_info:
            LineIndexedTranslation.model_validate(raw)

        failures = from_pydantic_error(exc_info.value)
        assert failures[0].error_type is ErreursType.OUTPUT_FORMAT_INVALID

    def test_duplicate_indices_emits_typed_error(self):
        raw = "<0/>a\n<1/>b\n<0/>c\n[=[END]=]"
        with pytest.raises(ValidationError) as exc_info:
            LineIndexedTranslation.model_validate(raw)

        failures = from_pydantic_error(exc_info.value)
        assert failures[0].error_type is ErreursType.DUPLICATE_INDICES
        assert failures[0].ctx["duplicate_indices"] == [0]


class TestHelpers:
    def test_line_indices(self):
        m = LineIndexedTranslation.model_validate("<2/>a\n<5/>b\n[=[END]=]")
        assert m.line_indices() == {2, 5}

    def test_fragments_at_unknown_raises_keyerror(self):
        m = LineIndexedTranslation.model_validate("<0/>x\n[=[END]=]")
        with pytest.raises(KeyError):
            m.fragments_at(42)

    def test_build_returns_plain_dict(self):
        m = LineIndexedTranslation.model_validate("<0/>x\n<1/>y\n[=[END]=]")
        built = m.build()
        assert built == {0: "x", 1: "y"}
        assert type(built) is dict


class TestMerge:
    def test_union_disjoint(self):
        a = LineIndexedTranslation.model_validate("<0/>a\n[=[END]=]")
        b = LineIndexedTranslation.model_validate("<1/>b\n[=[END]=]")
        merged = a.merge(b)
        assert merged.lines == {0: "a", 1: "b"}

    def test_other_overrides_on_common_indices(self):
        a = LineIndexedTranslation.model_validate("<0/>old\n<1/>keep\n[=[END]=]")
        b = LineIndexedTranslation.model_validate("<0/>new\n[=[END]=]")
        merged = a.merge(b)
        assert merged.lines == {0: "new", 1: "keep"}

    def test_idempotent_with_self(self):
        a = LineIndexedTranslation.model_validate("<0/>a\n<1/>b\n[=[END]=]")
        merged = a.merge(a)
        assert merged.lines == a.lines

    def test_does_not_mutate_inputs(self):
        a = LineIndexedTranslation.model_validate("<0/>a\n[=[END]=]")
        b = LineIndexedTranslation.model_validate("<0/>b\n[=[END]=]")
        _ = a.merge(b)
        assert a.lines == {0: "a"}
        assert b.lines == {0: "b"}
