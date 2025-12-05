"""Fixtures pour tests de validation."""

from unittest.mock import Mock

import pytest


@pytest.fixture
def mock_checks():
    """Liste de checks mockés pour tests de validation."""
    return [
        Mock(name="LineCountCheck"),
        Mock(name="FragmentCountCheck"),
        Mock(name="PunctuationCheck"),
    ]
