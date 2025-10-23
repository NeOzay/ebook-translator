import logging


class ConfigBase:
    # Attribut de classe pour le singleton
    _instance = None
    _locked: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def lock(self):
        self._locked = True

    def __setattr__(self, name, value):
        if getattr(self, "_locked", False):
            raise AttributeError("Configuration is locked")
        super().__setattr__(name, value)


class TemplateNames(ConfigBase):
    First_Pass_Template: str = "translate.jinja"
    Retry_Translation_Template: str = "retry_translation.jinja"
    Retry_Translation_Strict_Template: str = "retry_translation_strict.jinja"
    Missing_Lines_Template: str = "retry_missing_lines.jinja"  # Obsolète (re-traduit tout)
    Missing_Lines_Targeted_Template: str = "retry_missing_lines_targeted.jinja"  # Nouveau (seulement lignes manquantes)
    Refine_Template: str = "refine.jinja"  # Phase 2 affinage


class Logger_Level(ConfigBase):
    level: int = logging.INFO
    console_level: int = logging.ERROR
    file_level: int = logging.DEBUG


def lock_config():
    """Verrouille la configuration pour empêcher les modifications ultérieures."""
    Logger_Level().lock()
    TemplateNames().lock()
