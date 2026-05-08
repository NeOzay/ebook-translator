"""Tests de `ValidationFailure` et `from_pydantic_error`."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError, model_validator
from pydantic_core import PydanticCustomError

from ebook_translator.validation.diagnostics import (
    ErreursType,
    LinesMissingDiagnostic,
)
from ebook_translator.validation.failure import ValidationFailure, from_pydantic_error


class TestValidationFailureConstruction:
    def test_minimal_construction(self):
        f: ValidationFailure[LinesMissingDiagnostic] = ValidationFailure(
            error_type=ErreursType.LINES_MISSING,
            msg="2 lignes absentes",
            ctx={"missing_indices": [3, 7]},
        )
        assert f.error_type is ErreursType.LINES_MISSING
        assert f.ctx["missing_indices"] == [3, 7]
        assert f.loc == ()

    def test_str_enum_coercion(self):
        f: ValidationFailure[LinesMissingDiagnostic] = ValidationFailure(
            error_type="lines_missing",  # type: ignore[arg-type]
            msg="x",
            ctx={"missing_indices": []},
        )
        assert f.error_type is ErreursType.LINES_MISSING
        assert f.error_type == "lines_missing"

    def test_loc_preserved(self):
        f: ValidationFailure[LinesMissingDiagnostic] = ValidationFailure(
            error_type=ErreursType.LINES_MISSING,
            msg="x",
            ctx={"missing_indices": []},
            loc=("body", 0, "line"),
        )
        assert f.loc == ("body", 0, "line")

    def test_is_frozen(self):
        f: ValidationFailure[LinesMissingDiagnostic] = ValidationFailure(
            error_type=ErreursType.LINES_MISSING,
            msg="x",
            ctx={"missing_indices": []},
        )
        with pytest.raises(ValidationError):
            f.error_type = ErreursType.SENTENCE_INVALID  # type: ignore[misc]

    def test_json_serializable(self):
        f: ValidationFailure[LinesMissingDiagnostic] = ValidationFailure(
            error_type=ErreursType.LINES_MISSING,
            msg="x",
            ctx={"missing_indices": [1]},
        )
        dumped = f.model_dump_json()
        assert '"lines_missing"' in dumped


class _ModelWithKnownError(BaseModel):
    raw: str

    @model_validator(mode="after")
    def _check(self) -> _ModelWithKnownError:
        if "X" not in self.raw:
            raise PydanticCustomError(
                "lines_missing",
                "lignes absentes",
                {"missing_indices": [1, 2]},
            )
        return self


class _ModelWithUnknownError(BaseModel):
    raw: str

    @model_validator(mode="after")
    def _check(self) -> _ModelWithUnknownError:
        if "X" not in self.raw:
            raise PydanticCustomError(
                "totally_unmapped_error",
                "boom",
                {"detail": "x"},
            )
        return self


class TestFromPydanticError:
    def test_known_custom_error_round_trip(self):
        with pytest.raises(ValidationError) as exc_info:
            _ModelWithKnownError(raw="abc")

        failures = from_pydantic_error(exc_info.value)
        assert len(failures) == 1
        f = failures[0]
        assert f.error_type is ErreursType.LINES_MISSING
        assert f.msg == "lignes absentes"
        assert f.ctx == {"missing_indices": [1, 2]}

    def test_unknown_error_type_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            _ModelWithUnknownError(raw="abc")

        with pytest.raises(ValueError, match="totally_unmapped_error"):
            from_pydantic_error(exc_info.value)
