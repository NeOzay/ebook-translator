"""
Tests d'intégration pour le logging des requêtes LLM.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.ebook_translator.llm import LLM
from src.ebook_translator.logger import LogSession, get_session_log_path


@pytest.fixture(autouse=True)
def reset_log_session():
    """Reset la session de logs entre chaque test."""
    LogSession.reset()
    yield
    LogSession.reset()


@pytest.fixture
def mock_openai_client():
    """Mock du client OpenAI pour éviter les appels réels."""
    with patch("src.ebook_translator.llm.OpenAI") as mock:
        # Créer un mock de completion
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Mocked translation"

        # Configurer le mock pour retourner la réponse
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock.return_value = mock_client

        yield mock


@pytest.fixture
def llm_instance(mock_openai_client):
    """Crée une instance LLM avec un client mocké."""
    llm = LLM(
        model_name="test-model",
        url="https://api.test.com",
        api_key="test-key",
    )
    return llm


def test_llm_creates_log_with_context(llm_instance):
    """Test que le LLM crée un log avec le contexte approprié."""
    # Appeler query avec un contexte
    result = llm_instance.query(
        system_prompt="Translate this",
        content="Hello world",
        context="chunk_001",
    )

    # Vérifier que la requête a réussi
    assert result == "Mocked translation"

    # Vérifier que le fichier de log a été créé avec le bon nom
    session_dir = LogSession.get_session_dir()
    log_files = list(session_dir.glob("llm_chunk_001_*.log"))

    assert len(log_files) == 1, "Un fichier de log doit avoir été créé"

    # Vérifier le contenu du log
    log_content = log_files[0].read_text(encoding="utf-8")
    assert "=== LLM REQUEST LOG ===" in log_content
    assert "Context   : chunk_001" in log_content
    assert "Translate this" in log_content
    assert "Hello world" in log_content
    assert "Mocked translation" in log_content


def test_llm_creates_log_without_context(llm_instance):
    """Test que le LLM crée un log sans contexte (fallback)."""
    # Compter les fichiers avant
    session_dir = LogSession.get_session_dir()
    initial_files = list(session_dir.glob("llm_*.log"))
    initial_count = len(initial_files)

    result = llm_instance.query(
        system_prompt="Translate this",
        content="Hello world",
    )

    assert result == "Mocked translation"

    # Vérifier qu'un nouveau fichier a été créé
    log_files = list(session_dir.glob("llm_*.log"))
    assert len(log_files) == initial_count + 1, "Un fichier de log doit avoir été créé"

    # Trouver le nouveau fichier (dernier créé)
    new_file = sorted(log_files, key=lambda p: p.stat().st_mtime)[-1]

    # Le nom doit être llm_<counter>.log (sans contexte)
    # Format: llm_NNNN.log (sans underscore additionnel avant le numéro)
    assert new_file.name.startswith("llm_")
    assert new_file.name.endswith(".log")
    # Vérifier qu'il n'y a pas de contexte dans le nom (pas de double underscore)
    # Format attendu: llm_0002.log, pas llm_context_0002.log
    parts = new_file.stem.split("_")
    assert len(parts) == 2, f"Format attendu: llm_NNNN, reçu: {new_file.stem}"

    # Vérifier que le contexte est marqué N/A
    log_content = new_file.read_text(encoding="utf-8")
    assert "Context   : N/A" in log_content


def test_llm_multiple_queries_increment_counter(llm_instance):
    """Test que plusieurs requêtes incrémentent le compteur."""
    # Faire plusieurs requêtes
    llm_instance.query("Prompt 1", "Content 1", context="test")
    llm_instance.query("Prompt 2", "Content 2", context="test")
    llm_instance.query("Prompt 3", "Content 3", context="test")

    # Vérifier qu'on a 3 fichiers différents
    session_dir = LogSession.get_session_dir()
    log_files = sorted(session_dir.glob("llm_test_*.log"))

    assert len(log_files) == 3, "3 fichiers de log doivent avoir été créés"

    # Vérifier les noms (compteur)
    assert "llm_test_0001.log" in log_files[0].name
    assert "llm_test_0002.log" in log_files[1].name
    assert "llm_test_0003.log" in log_files[2].name


def test_llm_log_only_created_on_response(llm_instance, mock_openai_client):
    """Test que le fichier de log n'est créé qu'après la réponse (lazy)."""
    # Configurer le mock pour planter avant la réponse
    mock_openai_client.return_value.chat.completions.create.side_effect = Exception(
        "Network error"
    )

    # Appeler query (doit échouer)
    result = llm_instance.query("Prompt", "Content", context="error_test")

    # Vérifier que l'erreur a été retournée
    assert "[ERREUR INCONNUE:" in result

    # Le fichier de log doit quand même exister (créé lors de _append_response)
    session_dir = LogSession.get_session_dir()
    log_files = list(session_dir.glob("llm_error_test_*.log"))

    assert len(log_files) == 1, "Le fichier de log doit être créé même en cas d'erreur"

    # Vérifier que le contenu contient l'erreur
    log_content = log_files[0].read_text(encoding="utf-8")
    assert "[ERREUR INCONNUE:" in log_content


def test_llm_context_formats():
    """Test différents formats de contexte."""
    with patch("src.ebook_translator.llm.OpenAI") as mock:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "OK"
        mock.return_value.chat.completions.create.return_value = mock_response

        llm = LLM("test", "https://test.com", api_key="test")

        # Tester différents contextes
        contexts = [
            "chunk_001",
            "retry_chunk_005",
            "phase1_chunk_042",
            "correction_strict",
        ]

        for ctx in contexts:
            llm.query("Test", "Test", context=ctx)

        # Vérifier que tous les fichiers ont été créés
        session_dir = LogSession.get_session_dir()
        for ctx in contexts:
            log_files = list(session_dir.glob(f"llm_{ctx}_*.log"))
            assert len(log_files) >= 1, f"Log file for context '{ctx}' should exist"
