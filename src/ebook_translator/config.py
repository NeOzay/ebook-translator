import logging
from typing import Any


class ConfigBase:
    # Attribut de classe pour le singleton
    _instance = None
    _locked: bool = False

    def __new__(cls, *args: Any, **kwargs: Any):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def lock(self):
        self._locked = True

    def unlock(self):
        self._locked = False

    def __setattr__(self, name: str, value: Any):
        if getattr(self, "_locked", False):
            raise AttributeError("Configuration is locked")
        super().__setattr__(name, value)


class Logger_Level(ConfigBase):
    level: int = logging.INFO
    console_level: int = logging.ERROR
    file_level: int = logging.DEBUG


class Config(ConfigBase):
    DEFAULT_ENCODING = "o200k_base"
    """ Encodage par défaut pour le comptage de tokens (OpenAI o200k_base)"""


def lock_config():
    """Verrouille la configuration pour empêcher les modifications ultérieures."""
    Logger_Level().lock()
    Config().lock()


def unlock_config():
    """Déverrouille la configuration pour permettre les modifications."""
    Logger_Level().unlock()
    Config().unlock()
