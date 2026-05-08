"""
Tests for LLM exchange logging via LLMLogger.
"""

from unittest.mock import MagicMock

import pytest
from src.ebook_translator.llm.llm import LLM
from src.ebook_translator.llm.llm_config import LLMResponse
from src.ebook_translator.logger import LogSession


@pytest.fixture(autouse=True)
def reset_log_session():
    """Reset la session de logs entre chaque test."""
    LogSession.reset()
    yield
    LogSession.reset()


def _make_response(
    content: str = "Mocked translation", reasoning: str | None = None
) -> LLMResponse:
    return LLMResponse(
        content=content,
        reasoning=reasoning,
        tool_calls=None,
        finish_reason="stop",
        prompt_tokens=10,
        completion_tokens=5,
        cached_tokens=0,
        reasoning_tokens=0,
        model="test-model",
        response_id="test-id",
    )


@pytest.fixture
def mock_client():
    """Mock du client compatible avec ClientProviderProtocol."""
    client = MagicMock()
    client.parameters = {"model": "test-model"}
    client.request.return_value = _make_response()
    return client


@pytest.fixture
def llm_instance(mock_client):
    """Crée une instance LLM avec un client mocké."""
    return LLM(client=mock_client)


def test_llm_creates_log_with_context(llm_instance):
    """Test que le LLM crée un log avec le contexte approprié."""
    result = llm_instance.query(
        system_prompt="Translate this",
        content="Hello world",
        log_name="chunk_001",
    )

    assert result == "Mocked translation"

    session_dir = LogSession.get_session_dir()
    log_files = list(session_dir.glob("llm_chunk_001_*.log"))

    assert len(log_files) == 1, "Un fichier de log doit avoir été créé"

    log_content = log_files[0].read_text(encoding="utf-8")
    assert "=== LLM REQUEST LOG ===" in log_content
    assert "Context   : chunk_001" in log_content
    assert "Translate this" in log_content
    assert "Hello world" in log_content
    assert "Mocked translation" in log_content


def test_llm_creates_log_without_context(llm_instance):
    """Test que le LLM crée un log sans contexte (fallback)."""
    session_dir = LogSession.get_session_dir()
    initial_count = len(list(session_dir.glob("llm_*.log")))

    result = llm_instance.query(
        system_prompt="Translate this",
        content="Hello world",
    )

    assert result == "Mocked translation"

    log_files = list(session_dir.glob("llm_*.log"))
    assert len(log_files) == initial_count + 1, "Un fichier de log doit avoir été créé"

    new_file = sorted(log_files, key=lambda p: p.stat().st_mtime)[-1]
    assert new_file.name.startswith("llm_")
    assert new_file.name.endswith(".log")
    # Format without context: llm_NNNN_<timestamp>.log → stem parts ≥ 2
    parts = new_file.stem.split("_")
    assert parts[0] == "llm"
    assert parts[1].isdigit(), f"Expected counter segment, got: {parts[1]}"

    log_content = new_file.read_text(encoding="utf-8")
    assert "Context   : N/A" in log_content


def test_llm_multiple_queries_increment_counter(llm_instance):
    """Test que plusieurs requêtes incrémentent le compteur."""
    llm_instance.query("Prompt 1", "Content 1", log_name="test")
    llm_instance.query("Prompt 2", "Content 2", log_name="test")
    llm_instance.query("Prompt 3", "Content 3", log_name="test")

    session_dir = LogSession.get_session_dir()
    log_files = sorted(session_dir.glob("llm_test_*.log"))

    assert len(log_files) == 3, "3 fichiers de log doivent avoir été créés"

    # Counter segments are present in each filename
    assert "_0001_" in log_files[0].name
    assert "_0002_" in log_files[1].name
    assert "_0003_" in log_files[2].name


def test_llm_log_created_on_error(mock_client):
    """Test que le fichier de log est créé même en cas d'erreur."""
    mock_client.request.side_effect = Exception("Network error")
    llm_instance = LLM(client=mock_client)

    result = llm_instance.query("Prompt", "Content", log_name="error_test")

    assert "[ERREUR INCONNUE:" in result

    session_dir = LogSession.get_session_dir()
    log_files = list(session_dir.glob("llm_error_test_*.log"))

    assert len(log_files) == 1, "Le fichier de log doit être créé même en cas d'erreur"

    log_content = log_files[0].read_text(encoding="utf-8")
    assert "[ERREUR INCONNUE:" in log_content


def test_llm_context_formats(mock_client):
    """Test différents formats de contexte."""
    llm = LLM(client=mock_client)

    contexts = [
        "chunk_001",
        "retry_chunk_005",
        "phase1_chunk_042",
        "correction_strict",
    ]

    for ctx in contexts:
        llm.query("Test", "Test", log_name=ctx)

    session_dir = LogSession.get_session_dir()
    for ctx in contexts:
        log_files = list(session_dir.glob(f"llm_{ctx}_*.log"))
        assert len(log_files) >= 1, f"Log file for context '{ctx}' should exist"
