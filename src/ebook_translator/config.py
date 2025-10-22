from dataclasses import dataclass


@dataclass
class Config:
    First_Pass_Template: str = "translation.jinja"
    Retry_Translation_Template: str = "retry_translation.jinja"
    Retry_Translation_Strict_Template: str = "retry_translation_strict.jinja"
    Missing_Lines_Template: str = "retry_missing_lines.jinja"
    Refine_Template: str = "refine.jinja"  # Phase 2 affinage
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
