"""Nom de programme partagé par les lignes de commande."""

import sys

import pytest

from ebook_translator.audit.__main__ import MODULE_INVOCATION as AUDIT_MODULE
from ebook_translator.bench.__main__ import MODULE_INVOCATION as BENCH_MODULE
from ebook_translator.cli import program_name


class TestProgramName:
    """L'aide doit nommer la commande tapée, pas l'autre point d'entrée."""

    def test_script_installe_nomme_par_son_nom(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["/chemin/.venv/bin/ebook-audit", "cache"])

        assert program_name(AUDIT_MODULE) == "ebook-audit"

    def test_invocation_par_module_nomme_la_forme_longue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sous `-m`, `sys.argv[0]` vaut `__main__.py` : le nom d'aucune commande."""
        monkeypatch.setattr(sys, "argv", ["/chemin/audit/__main__.py"])

        assert program_name(AUDIT_MODULE) == "python -m ebook_translator.audit"

    def test_argv_vide_ne_leve_pas(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", [])

        assert program_name(BENCH_MODULE) == "python -m ebook_translator.bench"
