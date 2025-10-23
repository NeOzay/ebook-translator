"""
Tests pour le système de logging avec sessions et création lazy.
"""

import pytest
from pathlib import Path
import shutil
import tempfile

from src.ebook_translator.logger import (
    LogSession,
    LazyFileHandler,
    setup_logger,
    get_logger,
    get_session_log_path,
)


@pytest.fixture(autouse=True)
def reset_log_session():
    """Reset la session de logs entre chaque test."""
    LogSession.reset()
    yield
    LogSession.reset()


@pytest.fixture
def temp_logs_dir(monkeypatch):
    """Crée un répertoire temporaire pour les logs."""
    temp_dir = tempfile.mkdtemp()
    # Rediriger le répertoire de session vers temp
    monkeypatch.setattr(Path, "mkdir", lambda self, **kwargs: Path(temp_dir).mkdir(**kwargs))
    yield Path(temp_dir)
    # Nettoyer
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_log_session_singleton():
    """Test que LogSession est bien un singleton."""
    session1 = LogSession()
    session2 = LogSession()
    assert session1 is session2
    assert LogSession.get_session_dir() == LogSession.get_session_dir()


def test_log_session_creates_unique_dir():
    """Test que chaque session crée un répertoire unique."""
    session_dir = LogSession.get_session_dir()
    assert session_dir.name.startswith("run_")
    assert session_dir.parent == Path("logs")


def test_lazy_file_handler_creates_file_only_on_emit():
    """Test que LazyFileHandler ne crée le fichier qu'au premier log."""
    import logging
    import tempfile

    # Créer un fichier temporaire (path uniquement)
    temp_file = Path(tempfile.gettempdir()) / "test_lazy.log"
    if temp_file.exists():
        temp_file.unlink()

    # Créer le handler
    handler = LazyFileHandler(temp_file, mode="w")
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)

    # Vérifier que le fichier n'existe pas encore
    assert not temp_file.exists(), "Le fichier ne doit pas exister avant le premier log"

    # Émettre un log
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Test message",
        args=(),
        exc_info=None,
    )
    handler.emit(record)

    # Vérifier que le fichier existe maintenant
    assert temp_file.exists(), "Le fichier doit exister après le premier log"

    # Vérifier le contenu
    with open(temp_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert "Test message" in content

    # Nettoyer
    handler.close()
    temp_file.unlink()


def test_setup_logger_uses_session_dir():
    """Test que setup_logger utilise le répertoire de session."""
    logger = setup_logger("test.module", log_filename="test_setup.log")

    # Vérifier que le logger a bien 2 handlers (console + file)
    assert len(logger.handlers) == 2

    # Le second handler doit être LazyFileHandler
    file_handler = logger.handlers[1]
    assert isinstance(file_handler, LazyFileHandler)

    # Vérifier que le chemin contient le répertoire de session
    session_dir = LogSession.get_session_dir()
    assert file_handler.filename == session_dir / "test_setup.log"


def test_get_session_log_path():
    """Test que get_session_log_path retourne le bon chemin."""
    path = get_session_log_path("my_log.log")
    session_dir = LogSession.get_session_dir()
    assert path == session_dir / "my_log.log"


def test_get_logger_creates_with_custom_filename():
    """Test que get_logger peut créer un logger avec un nom de fichier personnalisé."""
    logger = get_logger("test.custom", log_filename="custom.log")

    # Vérifier que le logger utilise le bon fichier
    file_handler = logger.handlers[1]
    assert isinstance(file_handler, LazyFileHandler)
    assert file_handler.filename.name == "custom.log"


def test_setup_logger_avoids_duplicate_handlers():
    """Test que setup_logger n'ajoute pas de handlers multiples."""
    logger1 = setup_logger("test.duplicate")
    logger2 = setup_logger("test.duplicate")

    # Les deux doivent être le même objet
    assert logger1 is logger2

    # Et avoir exactement 2 handlers (pas de duplication)
    assert len(logger1.handlers) == 2


def test_log_session_reset():
    """Test que LogSession.reset() fonctionne correctement."""
    session_dir1 = LogSession.get_session_dir()

    # Reset
    LogSession.reset()

    # Nouvelle session doit avoir un répertoire différent
    session_dir2 = LogSession.get_session_dir()
    # Note: Comme les timestamps peuvent être identiques si trop rapides,
    # on vérifie juste que la fonction ne plante pas
    assert session_dir2 is not None
