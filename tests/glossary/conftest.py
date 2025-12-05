"""Fixtures pour tests glossaire."""

import pytest


@pytest.fixture
def sample_glossary():
    """Glossaire de test avec quelques entrées."""
    return {
        "Matrix": "Matrice",
        "Neo": "Néo",
        "Trinity": "Trinité",
    }
