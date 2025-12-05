"""Fixtures pour tests LLM."""

from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def mock_openai_client():
    """Client OpenAI mocké pour tests LLM."""
    client = Mock()
    client.chat.completions.create = AsyncMock()
    return client
