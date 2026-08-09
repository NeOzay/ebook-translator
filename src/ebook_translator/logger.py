"""
Module de configuration du logging pour ebook-translator.

Ce module fournit une fonction centralisée pour configurer le système de logging
avec sortie console et fichier. Tous les modules de l'application peuvent utiliser
cette fonction pour obtenir un logger configuré de manière cohérente.

Fonctionnalités :
- Regroupement des logs par session d'exécution dans logs/run_YYYYMMDD_HHMMSS/
- Création différée des fichiers de log (évite fichiers vides)
- Nommage contextuel des fichiers (chunk_042.log, llm_translation.log, etc.)
- Redirection après coup de la session (`LogSession.redirect`), pour qu'un
  programme puisse imposer son répertoire malgré des loggers déjà configurés
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

from .config import Logger_Level

try:
    from tqdm import tqdm

    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False  # type: ignore


# ============================================================
# 🔹 Gestionnaire de session de logs
# ============================================================


class LogSession:
    """
    Gestionnaire singleton pour regrouper tous les logs d'une exécution.

    Crée un répertoire unique par session : logs/run_YYYYMMDD_HHMMSS/, que
    `redirect` permet de remplacer une fois les loggers déjà configurés.
    """

    _instance: LogSession | None = None
    _session_dir: Path | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Éviter la ré-initialisation
        if LogSession._session_dir is not None:
            return

        # Créer le répertoire de session au premier appel
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_dir = Path("logs")
        LogSession._session_dir = base_dir / f"run_{timestamp}"

    @classmethod
    def get_session_dir(cls) -> Path:
        """Retourne le répertoire de la session en cours."""
        if cls._session_dir is None:
            cls()  # Initialiser si pas encore fait
        assert cls._session_dir is not None
        return cls._session_dir

    @classmethod
    def redirect(cls, directory: Path | str) -> None:
        """Re-cible la session, et avec elle tous les loggers déjà configurés.

        Les loggers de module sont créés à l'**import** (`get_logger(__name__)`
        au niveau module), donc bien avant qu'un programme ait pu lire ses
        arguments. Chaque `LazyFileHandler` créé par `setup_logger` est pour
        cette raison inscrit à un registre, que cette méthode parcourt pour
        déplacer les fichiers de log sans recréer les loggers.

        Les records déjà écrits restent dans l'ancien fichier : seuls les
        suivants vont au nouvel emplacement.

        Args:
            directory: Nouveau répertoire de session. Créé au premier log.

        Example:
            >>> LogSession.redirect(Path("bench/runs/20260804_143000/logs"))
        """
        cls._session_dir = Path(directory)
        for handler in _FILE_HANDLERS:
            handler.set_directory(cls._session_dir)

    @classmethod
    def reset(cls):
        """Reset la session (utile pour les tests)."""
        cls._instance = None
        cls._session_dir = None
        _FILE_HANDLERS.clear()


# ============================================================
# 🔹 Handlers de logging
# ============================================================


class TqdmLoggingHandler(logging.Handler):
    """
    Handler de logging compatible avec tqdm.

    Utilise tqdm.write() pour afficher les logs sans perturber
    les barres de progression.
    """

    def __init__(self, level: int = logging.NOTSET):
        super().__init__(level)

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            if TQDM_AVAILABLE:
                tqdm.write(msg, file=sys.stderr)  # type: ignore
            else:
                # Fallback si tqdm non disponible
                sys.stderr.write(msg + "\n")
                sys.stderr.flush()
        except Exception:
            self.handleError(record)


class LazyFileHandler(logging.Handler):
    """
    Handler qui crée le fichier de log seulement au premier message.

    Évite la création de fichiers vides en cas d'erreur précoce
    ou si le logger n'est jamais utilisé.
    """

    def __init__(
        self,
        filename: Path,
        mode: str = "a",
        encoding: str = "utf-8",
        level: int = logging.NOTSET,
    ):
        super().__init__(level)
        self.filename = filename
        self.mode = mode
        self.encoding = encoding
        self._handler: logging.FileHandler | None = None

    def set_directory(self, directory: Path) -> None:
        """Déplace les écritures à venir dans un autre répertoire.

        Le nom du fichier est conservé — seul son répertoire change. Si le
        fichier était déjà ouvert, il est fermé ; il sera rouvert au prochain
        log, au nouvel emplacement.

        Args:
            directory: Répertoire cible. Créé au prochain log, pas ici.
        """
        if self._handler is not None:
            self._handler.close()
            self._handler = None
        self.filename = directory / self.filename.name

    def _ensure_handler(self):
        """Crée le FileHandler sous-jacent si pas encore fait."""
        if self._handler is not None:
            return
        # Créer le répertoire parent si nécessaire
        self.filename.parent.mkdir(parents=True, exist_ok=True)
        # Créer le FileHandler
        self._handler = logging.FileHandler(
            self.filename,
            mode=self.mode,
            encoding=self.encoding,
        )
        # Copier le formatter
        if self.formatter:
            self._handler.setFormatter(self.formatter)

    def emit(self, record: logging.LogRecord):
        """Émit un log, en créant le fichier si nécessaire."""
        try:
            self._ensure_handler()
            if self._handler:
                self._handler.emit(record)
        except Exception:
            self.handleError(record)

    def close(self):
        """Ferme le handler sous-jacent si existant."""
        if self._handler:
            self._handler.close()
        super().close()


_FILE_HANDLERS: list[LazyFileHandler] = []
"""Handlers fichier créés par `setup_logger`, cibles de `LogSession.redirect`.

Les loggers de module étant configurés à l'import, il n'y a pas d'autre moyen de
les re-cibler après coup : ce registre est le seul point où l'ensemble des
fichiers de log ouverts par l'application reste joignable.
"""


# ============================================================
# 🔹 Configuration des loggers
# ============================================================


def setup_logger(
    logger: logging.Logger,
    log_dir: str | None = None,
    level: int = Logger_Level.level,
    console_level: int = Logger_Level.console_level,
    file_level: int = Logger_Level.file_level,
    log_filename: str = "translation.log",
) -> logging.Logger:
    """
    Configure un logger avec sortie console et fichier.

    Args:
        name: Nom du logger (généralement __name__ du module)
        log_dir: Répertoire de session (None = auto via LogSession)
        level: Niveau de logging global du logger
        console_level: Niveau de logging pour la sortie console
        file_level: Niveau de logging pour le fichier
        log_filename: Nom du fichier de log (défaut: "translation.log")

    Returns:
        Logger configuré avec handlers console et fichier

    Example:
        >>> logger = setup_logger(__name__)
        >>> logger.info("Traduction démarrée")
        >>> logger.error("Erreur lors de la traduction", exc_info=True)

    Note:
        Les logs sont regroupés par session dans logs/run_YYYYMMDD_HHMMSS/
        Le fichier est créé seulement au premier log (LazyFileHandler)
    """
    logger.setLevel(level)

    # Éviter d'ajouter des handlers multiples si déjà configuré
    if logger.handlers:
        return logger

    # Format détaillé pour les logs
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - "
        "%(filename)s:%(lineno)d (%(funcName)s) - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Handler console compatible avec tqdm (affichage dans le terminal)
    console_handler = TqdmLoggingHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Handler fichier (sauvegarde dans logs/run_XXX/)
    session_dir = Path(log_dir) if log_dir else LogSession.get_session_dir()

    log_path = session_dir / log_filename
    file_handler = LazyFileHandler(
        filename=log_path,
        mode="a",
        encoding="utf-8",
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    _FILE_HANDLERS.append(file_handler)

    return logger


def get_logger(name: str, log_filename: str = "translation.log") -> logging.Logger:
    """
    Récupère un logger existant ou en crée un nouveau avec la configuration par défaut.

    Args:
        name: Nom du logger (généralement __name__ du module)
        log_filename: Nom du fichier de log (défaut: "translation.log")

    Returns:
        Logger configuré et prêt à l'emploi

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Message de log")

        >>> # Logger avec fichier spécifique
        >>> logger = get_logger(__name__, "validation.log")
        >>> logger.info("Validation démarrée")

    Note:
        Si le logger est déjà configuré (handlers présents), il est retourné tel quel.
        Sinon, il est configuré via setup_logger avec la configuration par défaut.
        Les logs sont regroupés dans logs/run_YYYYMMDD_HHMMSS/ automatiquement.
    """
    logger = logging.getLogger(name)

    # Si le logger n'a pas de handlers, le configurer
    if not logger.handlers:
        return setup_logger(logger, log_filename=log_filename)

    return logger


def get_session_log_path(filename: str) -> Path:
    """
    Retourne le chemin complet d'un fichier de log dans le répertoire de session.

    Args:
        filename: Nom du fichier de log (ex: "llm_chunk_042.log")

    Returns:
        Chemin complet: logs/run_YYYYMMDD_HHMMSS/filename

    Example:
        >>> path = get_session_log_path("llm_chunk_001.log")
        >>> print(path)
        logs/run_20251023_143022/llm_chunk_001.log
    """
    session_dir = LogSession.get_session_dir()
    return session_dir / filename
