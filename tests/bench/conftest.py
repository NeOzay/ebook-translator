"""Fixtures communes aux tests du banc d'essais."""

from collections.abc import Callable
from pathlib import Path

import pytest

CONFIG_TEMPLATE = """
from pathlib import Path

from ebook_translator.bench.suite import BenchSuite, Seed, Variant
from ebook_translator.pipeline.base import PhaseName

{corps}

suite = BenchSuite(
    epub=Path(r"{epub}"),
    variants=[
        Variant("a", {{"temperature": 0.5}}, build),
        Variant("b", {{"temperature": 1.0}}, build),
    ],
    {extra}
)
"""

BUILD_QUI_LEVE = """
def build(env):
    raise RuntimeError("fabrique cassée")
"""


@pytest.fixture
def epub(tmp_path: Path) -> Path:
    """EPUB source factice : seule son existence compte pour ces tests."""
    source = tmp_path / "source" / "Mon Livre.epub"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"PK\x03\x04")
    return source


@pytest.fixture
def write_config(tmp_path: Path, epub: Path) -> Callable[..., Path]:
    """Écrit un script de configuration de banc d'essais et renvoie son chemin."""

    def _write(corps: str = BUILD_QUI_LEVE, extra: str = "") -> Path:
        config = tmp_path / "config_bench.py"
        config.write_text(
            CONFIG_TEMPLATE.format(corps=corps, epub=epub, extra=extra),
            encoding="utf-8",
        )
        return config

    return _write
