"""Tests du registre `RETRY_REGISTRY`.

Vérifie quatre invariants :
1. couverture : tout `ErreursType` a une entrée dans `RETRY_REGISTRY` et
   dans `DIAGNOSTIC_BY_TYPE`,
2. chaque template `RetryTemplate` résout vers une paire de fichiers Jinja
   présents sur disque,
3. chaque `params_type` est une `TypedDict` exportée par
   `template.template_params`,
4. modes `replace` / `merge` conformes au plan.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import template.template_params as tp
from ebook_translator.llm.retry_registry import (
    RETRY_REGISTRY,
    SCHEMA_LEVEL_ERRORS,
    RetryEntry,
)
from ebook_translator.validation.diagnostics import DIAGNOSTIC_BY_TYPE, ErreursType

TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "src" / "template"


def _typeddict_names() -> set[str]:
    return {
        name
        for name, obj in inspect.getmembers(tp, inspect.isclass)
        if getattr(obj, "__module__", "") == tp.__name__
    }


class TestCoverage:
    def test_content_erreurs_types_have_registry_entry(self):
        assert set(RETRY_REGISTRY.keys()) == set(ErreursType) - SCHEMA_LEVEL_ERRORS

    def test_schema_errors_excluded_from_registry(self):
        for err in SCHEMA_LEVEL_ERRORS:
            assert err not in RETRY_REGISTRY

    def test_all_erreurs_types_have_diagnostic_mapping(self):
        assert set(DIAGNOSTIC_BY_TYPE.keys()) == set(ErreursType)


class TestRegistryShape:
    def test_all_entries_are_retry_entry(self):
        for entry in RETRY_REGISTRY.values():
            assert isinstance(entry, RetryEntry)

    def test_modes_are_valid(self):
        for entry in RETRY_REGISTRY.values():
            assert entry.mode in {"replace", "merge"}


class TestTemplatesExistOnDisk:
    def test_each_template_pair_resolvable(self):
        for error_type, entry in RETRY_REGISTRY.items():
            sys_rel, usr_rel = entry.template.get_templates()
            sys_file = TEMPLATE_ROOT / sys_rel
            usr_file = TEMPLATE_ROOT / usr_rel
            assert sys_file.is_file(), f"{error_type}: {sys_file} absent"
            assert usr_file.is_file(), f"{error_type}: {usr_file} absent"


class TestParamsTypesAreFromTemplateParams:
    def test_each_params_type_lives_in_template_params(self):
        known = _typeddict_names()
        for error_type, entry in RETRY_REGISTRY.items():
            assert entry.params_type.__name__ in known, (
                f"{error_type}: {entry.params_type.__name__} non exporté "
                f"par template.template_params"
            )


class TestModeSemanticsByErrorType:
    """Garde-fou : les choix `replace` / `merge` du plan ne dérivent pas."""

    EXPECTED_MODES = {
        ErreursType.LINES_MISSING: "merge",
        ErreursType.FRAGMENT_COUNT_MISMATCH: "replace",
        ErreursType.PUNCTUATION_MISMATCH: "replace",
        ErreursType.SENTENCE_INVALID: "merge",
    }

    def test_modes_match_plan(self):
        for error_type, expected in self.EXPECTED_MODES.items():
            assert RETRY_REGISTRY[error_type].mode == expected
