from enum import StrEnum
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


class TemplateNames(StrEnum):
    First_Pass_Template = "translate_base.jinja"
    Retry_Fragments_Template = "retry_correct_fragments.jinja"
    Retry_Fragments_Flexible_Template = "retry_correct_fragments_flexible.jinja"
    Retry_Missing_Lines_Targeted_Template = (
        "retry_translate_missing_lines_targeted.jinja"
    )
    Refine_Template = "translate_refine.jinja"
    Retry_Sentence_Template = "retry_translate_sentence.jinja"
    Retry_Punctuation_Template = "retry_correct_punctuation.jinja"


class Logger_Level(ConfigBase):
    level: int = logging.INFO
    console_level: int = logging.ERROR
    file_level: int = logging.DEBUG


def lock_config():
    """Verrouille la configuration pour empêcher les modifications ultérieures."""
    Logger_Level().lock()
