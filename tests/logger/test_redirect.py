"""
Tests de la redirection de session (`LogSession.redirect`).

Les loggers de module sont configurés à l'import, donc bien avant qu'un
programme ait pu lire ses arguments. La redirection est le seul moyen de leur
imposer un répertoire après coup — c'est ce qui rattache les logs d'une
variante de banc à son workspace.
"""

import logging
from collections.abc import Generator
from pathlib import Path

import pytest
from src.ebook_translator.logger import (
    LazyFileHandler,
    LogSession,
    get_logger,
    get_session_log_path,
)


@pytest.fixture(autouse=True)
def reset_log_session() -> Generator[None]:
    """Isole chaque test : session et registre de handlers repartent à neuf."""
    LogSession.reset()
    yield
    LogSession.reset()


def _fichier(logger: logging.Logger) -> Path:
    """Chemin visé par le `LazyFileHandler` d'un logger."""
    handler = logger.handlers[1]
    assert isinstance(handler, LazyFileHandler)
    return handler.filename


def test_redirection_avant_toute_emission(tmp_path: Path):
    """Un logger jamais utilisé écrit directement dans le nouveau répertoire."""
    logger = get_logger("test.redirect.avant", log_filename="a.log")

    LogSession.redirect(tmp_path / "cible")
    logger.error("après redirection")

    assert _fichier(logger) == tmp_path / "cible" / "a.log"
    assert (tmp_path / "cible" / "a.log").read_text(encoding="utf-8").strip()


def test_redirection_apres_emission(tmp_path: Path):
    """Le fichier déjà ouvert est fermé, la suite part au nouvel emplacement."""
    LogSession.redirect(tmp_path / "premier")
    logger = get_logger("test.redirect.apres", log_filename="b.log")
    logger.error("avant")

    ancien = tmp_path / "premier" / "b.log"
    assert "avant" in ancien.read_text(encoding="utf-8")

    LogSession.redirect(tmp_path / "second")
    logger.error("après")

    nouveau = tmp_path / "second" / "b.log"
    assert "après" in nouveau.read_text(encoding="utf-8")
    # Les records déjà écrits restent où ils étaient : on déplace les écritures
    # à venir, pas l'historique.
    assert "après" not in ancien.read_text(encoding="utf-8")


def test_redirection_couvre_tous_les_loggers(tmp_path: Path):
    """Un seul appel re-cible l'ensemble des loggers déjà configurés."""
    premier = get_logger("test.redirect.multi.un", log_filename="un.log")
    second = get_logger("test.redirect.multi.deux", log_filename="deux.log")

    LogSession.redirect(tmp_path / "tous")

    assert _fichier(premier) == tmp_path / "tous" / "un.log"
    assert _fichier(second) == tmp_path / "tous" / "deux.log"


def test_redirection_idempotente(tmp_path: Path):
    """Deux redirections vers le même répertoire n'empilent pas les chemins."""
    logger = get_logger("test.redirect.idem", log_filename="c.log")

    LogSession.redirect(tmp_path / "cible")
    LogSession.redirect(tmp_path / "cible")

    assert _fichier(logger) == tmp_path / "cible" / "c.log"


def test_logger_cree_apres_redirection(tmp_path: Path):
    """Un logger configuré après coup hérite du répertoire redirigé."""
    LogSession.redirect(tmp_path / "cible")

    logger = get_logger("test.redirect.tardif", log_filename="d.log")

    assert _fichier(logger) == tmp_path / "cible" / "d.log"


def test_get_session_log_path_suit_la_redirection(tmp_path: Path):
    """Les fichiers d'échange LLM suivent la redirection.

    `LLM._make_log_path` passe par `get_session_log_path` à chaque requête :
    c'est ce qui rapatrie les traces LLM dans le workspace de la variante.
    """
    LogSession.redirect(tmp_path / "cible")

    assert get_session_log_path("llm_0001.log") == tmp_path / "cible" / "llm_0001.log"


def test_reset_vide_le_registre(tmp_path: Path):
    """Après reset, les anciens handlers ne sont plus re-ciblés."""
    logger = get_logger("test.redirect.reset", log_filename="e.log")
    avant = _fichier(logger)

    LogSession.reset()
    LogSession.redirect(tmp_path / "cible")

    assert _fichier(logger) == avant
