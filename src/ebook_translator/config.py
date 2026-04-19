import logging
from enum import StrEnum
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


class Template(StrEnum):
    def __init__(self, s: str) -> None:
        self.prefix = ""

    def get_templates(self) -> tuple[str, str]:
        prefix = self.prefix
        return prefix + self + "_system.jinja", prefix + self + "_user.jinja"

    def get_system(self) -> str:
        return self.prefix + self + "_system.jinja"

    def get_user(self) -> str:
        return self.prefix + self + "_user.jinja"


class PhaseTemplate(Template):
    def __init__(self, s: str) -> None:
        self.prefix = "phase/"

    Analyze_Chapter = "analyze_chapter"
    First_Pass_Template = "translate_base"
    Refine_Template = "translate_refine"
    Glossary = "glossary"


class RetryTemplate(Template):
    def __init__(self, s: str) -> None:
        self.prefix = "retry/"

    Retry_Analysis_Invalid_Json_Template = "retry_correct_analysis_invalid_json"
    Retry_Analysis_Missing_Sections_Template = "retry_correct_analysis_missing_sections"
    Retry_Fragments_Template = "retry_correct_fragments"
    Retry_Missing_Lines_Targeted_Template = "retry_translate_missing_lines_targeted"
    Retry_Sentence_Template = "retry_translate_sentence"
    Retry_Punctuation_Template = "retry_correct_punctuation"


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
