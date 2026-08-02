"""Fixtures pour tests glossaire."""

import pytest

from template.phase.glossary_models import LLMTermeGlossary


@pytest.fixture
def sample_entries() -> list[LLMTermeGlossary]:
    """Entrées de glossaire telles que produites par `LLMGlossaryModel.build()`."""
    return [
        {
            "terme": "matrix",
            "type": "terme_technique",
            "sexe": "nc",
            "proposition_traduction": "matrice",
        },
        {
            "terme": "neo",
            "type": "personnage",
            "sexe": "m",
            "proposition_traduction": "néo",
        },
        {
            "terme": "trinity",
            "type": "personnage",
            "sexe": "f",
            "proposition_traduction": "trinité",
        },
    ]
