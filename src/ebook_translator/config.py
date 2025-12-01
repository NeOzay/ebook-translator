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

    def __setattr__(self, name: str, value: Any):
        if getattr(self, "_locked", False):
            raise AttributeError("Configuration is locked")
        super().__setattr__(name, value)


class TemplateNames(StrEnum):
    # Phase 0: Analyse littéraire
    Analyze_Incremental = "analyze_chapter_incremental.jinja"
    Analyze_Simplified_Template = "analyze_chapter_simplified.jinja"
    Chapter_Grouping_Template = "chapter_grouping.jinja"
    Retry_Analysis_Invalid_Json_Template = "retry_correct_analysis_invalid_json.jinja"
    Retry_Analysis_Missing_Sections_Template = (
        "retry_correct_analysis_missing_sections.jinja"
    )

    # Phase 1: Traduction initiale
    First_Pass_Template = "translate_base.jinja"
    Retry_Fragments_Template = "retry_correct_fragments.jinja"
    Retry_Fragments_Flexible_Template = "retry_correct_fragments_flexible.jinja"
    Retry_Missing_Lines_Targeted_Template = (
        "retry_translate_missing_lines_targeted.jinja"
    )
    Retry_Sentence_Template = "retry_translate_sentence.jinja"

    # Phase 2: Raffinement
    Refine_Template = "translate_refine.jinja"
    Retry_Punctuation_Template = "retry_correct_punctuation.jinja"


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
