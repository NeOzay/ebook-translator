"""
Module de configuration du logging pour ebook-translator.

Ce module fournit une fonction centralisée pour configurer le système de logging
avec sortie console et fichier. Tous les modules de l'application peuvent utiliser
cette fonction pour obtenir un logger configuré de manière cohérente.
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

try:
    from tqdm import tqdm

    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False


class TqdmLoggingHandler(logging.Handler):
    """
    Handler de logging compatible avec tqdm.

    Utilise tqdm.write() pour afficher les logs sans perturber
    les barres de progression.
    """

    def __init__(self, level=logging.NOTSET):
        super().__init__(level)

    def emit(self, record):
        try:
            msg = self.format(record)
            if TQDM_AVAILABLE:
                tqdm.write(msg, file=sys.stderr)
            else:
                # Fallback si tqdm non disponible
                sys.stderr.write(msg + "\n")
                sys.stderr.flush()
        except Exception:
            self.handleError(record)


def setup_logger(
    name: str,
    log_dir: str = "logs",
    level: int = logging.INFO,
    console_level: int = logging.ERROR,
    file_level: int = logging.DEBUG,
) -> logging.Logger:
    """
    Configure un logger avec sortie console et fichier.

    Args:
        name: Nom du logger (généralement __name__ du module)
        log_dir: Répertoire où sauvegarder les fichiers de log
        level: Niveau de logging global du logger
        console_level: Niveau de logging pour la sortie console
        file_level: Niveau de logging pour le fichier

    Returns:
        Logger configuré avec handlers console et fichier

    Example:
        >>> logger = setup_logger(__name__)
        >>> logger.info("Traduction démarrée")
        >>> logger.error("Erreur lors de la traduction", exc_info=True)
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Éviter d'ajouter des handlers multiples si déjà configuré
    if logger.handlers:
        return logger

    # Format détaillé pour les logs
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Handler console compatible avec tqdm (affichage dans le terminal)
    console_handler = TqdmLoggingHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Handler fichier (sauvegarde dans logs/)
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_handler = logging.FileHandler(
        log_path / f"translation_{timestamp}.log",
        encoding="utf-8",
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Récupère un logger existant ou en crée un nouveau avec la configuration par défaut.

    Args:
        name: Nom du logger (généralement __name__ du module)

    Returns:
        Logger configuré

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Message de log")
    """
    logger = logging.getLogger(name)

    # Si le logger n'a pas de handlers, le configurer
    if not logger.handlers:
        return setup_logger(name)

    return logger
