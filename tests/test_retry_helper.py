"""Tests pour le helper de retry avec mode raisonnement."""

import pytest
from unittest.mock import Mock, MagicMock
from ebook_translator.checks.retry_helper import retry_with_reasoning
from ebook_translator.checks.base import ValidationContext
from ebook_translator.segment import Chunk


def create_mock_context(llm_mock: Mock | None = None) -> ValidationContext:
    """Crée un contexte de validation mock pour les tests."""
    chunk = Chunk(index=42)

    if llm_mock is None:
        llm_mock = Mock()

    context = ValidationContext(
        chunk=chunk,
        translated_texts={0: "Test translation"},
        original_texts={0: "Test original"},
        llm=llm_mock,
        target_language="fr",
        phase="initial",
        max_retries=2,
        filtered_lines=[],
    )

    return context


def test_retry_success_first_attempt():
    """Le retry réussit dès la première tentative (mode normal)."""
    # Setup
    llm_mock = Mock()
    llm_mock.query.return_value = "Corrected output"
    context = create_mock_context(llm_mock)

    render_calls = []
    def render_prompt(use_reasoning: bool) -> str:
        render_calls.append(use_reasoning)
        return "Test prompt"

    validate_calls = []
    def validate_result(llm_output: str) -> bool:
        validate_calls.append(llm_output)
        return True  # Succès immédiat

    # Execute
    success, result = retry_with_reasoning(
        context=context,
        chunk_index=42,
        render_prompt=render_prompt,
        validate_result=validate_result,
        context_name="test",
        max_attempts=2,
    )

    # Assert
    assert success is True
    assert result == "Corrected output"
    assert len(render_calls) == 1
    assert render_calls[0] is False  # Première tentative = mode normal
    assert len(validate_calls) == 1
    assert validate_calls[0] == "Corrected output"

    # Vérifier que LLM a été appelé avec use_reasoning_mode=False
    llm_mock.query.assert_called_once()
    call_kwargs = llm_mock.query.call_args.kwargs
    assert call_kwargs["use_reasoning_mode"] is False
    assert "correction_test_chunk_042_attempt_1" in call_kwargs["context"]


def test_retry_success_second_attempt():
    """Le retry réussit à la deuxième tentative (mode reasoning)."""
    # Setup
    llm_mock = Mock()
    llm_mock.query.side_effect = [
        "First attempt output",
        "Second attempt output with reasoning",
    ]
    context = create_mock_context(llm_mock)

    render_calls = []
    def render_prompt(use_reasoning: bool) -> str:
        render_calls.append(use_reasoning)
        return f"Prompt (reasoning={use_reasoning})"

    validate_calls = []
    def validate_result(llm_output: str) -> bool:
        validate_calls.append(llm_output)
        # Première tentative échoue, deuxième réussit
        return len(validate_calls) == 2

    # Execute
    success, result = retry_with_reasoning(
        context=context,
        chunk_index=42,
        render_prompt=render_prompt,
        validate_result=validate_result,
        context_name="test",
        max_attempts=2,
    )

    # Assert
    assert success is True
    assert result == "Second attempt output with reasoning"
    assert len(render_calls) == 2
    assert render_calls[0] is False  # Première tentative = mode normal
    assert render_calls[1] is True   # Deuxième tentative = mode reasoning
    assert len(validate_calls) == 2

    # Vérifier que LLM a été appelé 2 fois
    assert llm_mock.query.call_count == 2

    # Vérifier première tentative (mode normal)
    first_call = llm_mock.query.call_args_list[0]
    assert first_call.kwargs["use_reasoning_mode"] is False
    assert "attempt_1" in first_call.kwargs["context"]
    assert "reasoning" not in first_call.kwargs["context"]

    # Vérifier deuxième tentative (mode reasoning)
    second_call = llm_mock.query.call_args_list[1]
    assert second_call.kwargs["use_reasoning_mode"] is True
    assert "attempt_2_reasoning" in second_call.kwargs["context"]


def test_retry_failure_all_attempts():
    """Le retry échoue après toutes les tentatives."""
    # Setup
    llm_mock = Mock()
    llm_mock.query.side_effect = [
        "First attempt output",
        "Second attempt output",
    ]
    context = create_mock_context(llm_mock)

    def render_prompt(use_reasoning: bool) -> str:
        return "Test prompt"

    validate_calls = []
    def validate_result(llm_output: str) -> bool:
        validate_calls.append(llm_output)
        return False  # Toujours échoue

    # Execute
    success, result = retry_with_reasoning(
        context=context,
        chunk_index=42,
        render_prompt=render_prompt,
        validate_result=validate_result,
        context_name="test",
        max_attempts=2,
    )

    # Assert
    assert success is False
    assert result is None
    assert len(validate_calls) == 2
    assert llm_mock.query.call_count == 2


def test_retry_llm_error():
    """Gestion des erreurs LLM."""
    # Setup
    llm_mock = Mock()
    llm_mock.query.side_effect = [
        Exception("LLM error on first attempt"),
        "Second attempt output",
    ]
    context = create_mock_context(llm_mock)

    def render_prompt(use_reasoning: bool) -> str:
        return "Test prompt"

    validate_calls = []
    def validate_result(llm_output: str) -> bool:
        validate_calls.append(llm_output)
        return True

    # Execute
    success, result = retry_with_reasoning(
        context=context,
        chunk_index=42,
        render_prompt=render_prompt,
        validate_result=validate_result,
        context_name="test",
        max_attempts=2,
    )

    # Assert
    assert success is True  # Réussit à la deuxième tentative
    assert result == "Second attempt output"
    assert len(validate_calls) == 1  # validate_result appelé 1 seule fois (2e tentative)
    assert llm_mock.query.call_count == 2


def test_retry_no_llm():
    """Erreur si LLM est None."""
    # Setup
    context = create_mock_context(llm_mock=None)
    context.llm = None

    def render_prompt(use_reasoning: bool) -> str:
        return "Test prompt"

    def validate_result(llm_output: str) -> bool:
        return True

    # Execute
    success, result = retry_with_reasoning(
        context=context,
        chunk_index=42,
        render_prompt=render_prompt,
        validate_result=validate_result,
        context_name="test",
        max_attempts=2,
    )

    # Assert
    assert success is False
    assert result is None


def test_retry_context_naming():
    """Vérification du nommage des contextes de log."""
    # Setup
    llm_mock = Mock()
    llm_mock.query.return_value = "Output"
    context = create_mock_context(llm_mock)

    def render_prompt(use_reasoning: bool) -> str:
        return "Test prompt"

    def validate_result(llm_output: str) -> bool:
        return False  # Toujours échoue pour tester les 2 tentatives

    # Execute
    retry_with_reasoning(
        context=context,
        chunk_index=99,
        render_prompt=render_prompt,
        validate_result=validate_result,
        context_name="fragment_line_5",
        max_attempts=2,
    )

    # Assert
    assert llm_mock.query.call_count == 2

    # Vérifier première tentative (mode normal)
    first_call = llm_mock.query.call_args_list[0]
    assert first_call.kwargs["context"] == "correction_fragment_line_5_chunk_099_attempt_1"

    # Vérifier deuxième tentative (mode reasoning)
    second_call = llm_mock.query.call_args_list[1]
    assert second_call.kwargs["context"] == "correction_fragment_line_5_chunk_099_attempt_2_reasoning"


def test_retry_validate_exception():
    """Validation qui lève une exception est traitée comme un échec."""
    # Setup
    llm_mock = Mock()
    llm_mock.query.side_effect = [
        "First attempt output",
        "Second attempt output",
    ]
    context = create_mock_context(llm_mock)

    def render_prompt(use_reasoning: bool) -> str:
        return "Test prompt"

    validate_calls = []
    def validate_result(llm_output: str) -> bool:
        validate_calls.append(llm_output)
        if len(validate_calls) == 1:
            raise ValueError("Validation error")
        return True  # Deuxième tentative réussit

    # Execute
    success, result = retry_with_reasoning(
        context=context,
        chunk_index=42,
        render_prompt=render_prompt,
        validate_result=validate_result,
        context_name="test",
        max_attempts=2,
    )

    # Assert
    assert success is True  # Réussit à la deuxième tentative
    assert result == "Second attempt output"
    assert len(validate_calls) == 2
    assert llm_mock.query.call_count == 2
