"""Fixtures communes aux tests du banc d'essais."""

from collections.abc import Callable, Generator
from pathlib import Path

import pytest

from ebook_translator.logger import _FILE_HANDLERS, LogSession


@pytest.fixture(autouse=True)
def restaure_la_session_de_logs() -> Generator[None]:
    """Annule les redirections de logs faites par le harness ou le worker.

    `run_suite` et `worker.main` re-ciblent les loggers du processus vers le
    run qu'ils créent. Sans restauration, un test enverrait les logs des
    suivants dans son `tmp_path`, effacé entre-temps.
    """
    session = LogSession._session_dir  # pyright: ignore[reportPrivateUsage]
    fichiers = [(handler, handler.filename) for handler in _FILE_HANDLERS]
    yield
    LogSession._session_dir = session  # pyright: ignore[reportPrivateUsage]
    for handler, filename in fichiers:
        handler.set_directory(filename.parent)


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

BUILD_QUI_TRAITE = """
from ebook_translator.pipeline.context import PhaseStats


class _Pipeline:
    def __init__(self, env):
        self.epub_path = env.epub
        self.cache_dir = env.cache_dir

    def run(self, **kwargs):
        return {{
            "traduction": PhaseStats(
                phase_name="traduction",
                chunks_total={total},
                chunks_processed={processed},
            )
        }}


class _Builder:
    def __init__(self, env):
        self._env = env

    def build(self):
        return _Pipeline(self._env), {{}}


def build(env):
    return _Builder(env)
"""
"""Fabrique qui va au bout, paramétrée par le travail accompli.

Sans elle, aucun test n'exerçait le chemin nominal de `worker.execute` : toutes
les fabriques levaient, et le calcul du statut d'une variante — ce qui empêche
un run vide de passer pour réussi — n'était donc vérifié nulle part.
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
