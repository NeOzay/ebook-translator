"""Tests du provider Mistral.

Aucun appel réseau : `Mistral` n'ouvre pas de connexion à la construction, et le
SDK est remplacé par un `MagicMock` là où un envoi est nécessaire.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from ebook_translator.llm.clients.mistral import (
    Mistral,
    MistralModels,
    _cache_key_for,  # pyright: ignore[reportPrivateUsage]
)
from ebook_translator.llm.clients.protocol import ClientProviderProtocol
from ebook_translator.llm.llm_config import GenericLLMConfig, LLMConfigExport

pytestmark = pytest.mark.llm_module


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Évite la lecture du `.env` et le `sys.exit(1)` de `get_api_key`."""
    monkeypatch.setenv("API_KEY", "sk-test-not-a-real-key")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)


@pytest.fixture
def client() -> Mistral:
    return Mistral(MistralModels.LARGE)


def _response(
    content: Any = "bonjour",
    usage: dict[str, Any] | None = None,
    finish_reason: str | None = "stop",
) -> MagicMock:
    """Construit une fausse `ChatCompletionResponse` réduite à ce que `parse` lit."""
    message = MagicMock()
    message.content = content
    message.tool_calls = None

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason

    usage_obj = MagicMock()
    payload = usage or {}
    usage_obj.prompt_tokens = payload.get("prompt_tokens", 10)
    usage_obj.completion_tokens = payload.get("completion_tokens", 5)
    usage_obj.model_extra = payload.get("model_extra", {})

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage_obj
    response.model = "mistral-large-latest"
    response.id = "cmpl-123"
    return response


class TestConstruction:
    def test_defaults_to_large(self, client: Mistral) -> None:
        assert client.parameters["model"] == "mistral-large-latest"

    def test_satisfies_provider_protocol(self, client: Mistral) -> None:
        assert isinstance(client, ClientProviderProtocol)

    def test_prefers_dedicated_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "mistral-specific-key")
        assert Mistral().mistral.sdk_configuration.security is not None

    def test_user_config_is_merged(self) -> None:
        client = Mistral(MistralModels.SMALL, config={"temperature": 0.3})
        assert client.parameters["model"] == "mistral-small-latest"
        assert client.parameters["temperature"] == 0.3


class TestConfigResolution:
    @pytest.mark.parametrize(
        ("strength", "expected"),
        [
            ("low", "mistral-small-latest"),
            ("high", "mistral-medium-latest"),
            ("max", "mistral-large-latest"),
        ],
    )
    def test_preset_maps_strength_to_model(self, strength: Any, expected: str) -> None:
        exported = Mistral.get_model_preset_config(strength, False)
        assert exported.properties["model"] == expected

    def test_generic_config_is_translated(self) -> None:
        resolved = Mistral._resolve_config(  # pyright: ignore[reportPrivateUsage]
            GenericLLMConfig(temperature=0.2, top_p=0.9, max_tokens=42)
        )
        assert resolved == {"temperature": 0.2, "top_p": 0.9, "max_tokens": 42}

    def test_use_thinking_is_dropped(self) -> None:
        """Aucun modèle Mistral visé n'expose de mode raisonnement."""
        resolved = Mistral._resolve_config(  # pyright: ignore[reportPrivateUsage]
            GenericLLMConfig(temperature=0.2, use_thinking="max")
        )
        assert "reasoning_effort" not in resolved
        assert "prompt_mode" not in resolved

    def test_exported_config_is_bound_to_the_provider(self) -> None:
        exported = Mistral.get_model_preset_config("max", False)
        assert isinstance(exported, LLMConfigExport)
        with pytest.raises(ValueError, match="Provider mismatch"):
            _ = exported.get_properties(MagicMock().__class__)

    def test_none_value_removes_the_key(self, client: Mistral) -> None:
        client.applied_config({"temperature": 0.7})
        assert client.parameters["temperature"] == 0.7
        client.applied_config({"temperature": None})
        assert "temperature" not in client.parameters


class TestPromptCacheKey:
    def test_key_is_derived_from_the_system_prompt(self) -> None:
        key = _cache_key_for([{"role": "system", "content": "SYS"}])
        assert key.startswith("ebt-")

    def test_same_system_prompt_yields_the_same_key(self) -> None:
        """C'est tout l'intérêt : le pipeline rejoue le même prompt système."""
        a = _cache_key_for(
            [{"role": "system", "content": "SYS"}, {"role": "user", "content": "un"}]
        )
        b = _cache_key_for(
            [{"role": "system", "content": "SYS"}, {"role": "user", "content": "deux"}]
        )
        assert a == b

    def test_different_system_prompts_yield_different_keys(self) -> None:
        a = _cache_key_for([{"role": "system", "content": "PHASE 1"}])
        b = _cache_key_for([{"role": "system", "content": "PHASE 2"}])
        assert a != b

    def test_request_sends_a_cache_key(self, client: Mistral) -> None:
        client.mistral = MagicMock()
        client.mistral.chat.complete.return_value = _response()

        _ = client.request("SYS", "USER")

        sent = client.mistral.chat.complete.call_args.kwargs
        assert sent["prompt_cache_key"] == _cache_key_for(sent["messages"])

    def test_explicit_cache_key_is_preserved(self, client: Mistral) -> None:
        client.mistral = MagicMock()
        client.mistral.chat.complete.return_value = _response()

        _ = client.request("SYS", "USER", config={"prompt_cache_key": "custom"})

        assert client.mistral.chat.complete.call_args.kwargs["prompt_cache_key"] == (
            "custom"
        )


class TestRequest:
    def test_sends_model_and_messages(self, client: Mistral) -> None:
        client.mistral = MagicMock()
        client.mistral.chat.complete.return_value = _response()

        result = client.request("SYS", "USER")

        sent = client.mistral.chat.complete.call_args.kwargs
        assert sent["model"] == "mistral-large-latest"
        assert sent["messages"] == [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "USER"},
        ]
        assert result.content == "bonjour"


class TestParse:
    def test_maps_the_response_fields(self, client: Mistral) -> None:
        parsed = client.parse(_response())

        assert parsed.content == "bonjour"
        assert parsed.finish_reason == "stop"
        assert parsed.prompt_tokens == 10
        assert parsed.completion_tokens == 5
        assert parsed.model == "mistral-large-latest"
        assert parsed.response_id == "cmpl-123"
        assert parsed.reasoning is None
        assert parsed.reasoning_tokens == 0

    def test_flattens_a_list_of_content_chunks(self, client: Mistral) -> None:
        chunk_a, chunk_b = MagicMock(), MagicMock()
        chunk_a.text, chunk_b.text = "bon", "jour"

        parsed = client.parse(_response(content=[chunk_a, chunk_b]))

        assert parsed.content == "bonjour"

    def test_handles_a_missing_content(self, client: Mistral) -> None:
        assert client.parse(_response(content=None)).content is None

    def test_reads_cached_tokens_from_model_extra(self, client: Mistral) -> None:
        """`prompt_tokens_details` n'est pas un champ typé du SDK, mais l'API l'envoie."""
        response = _response(
            usage={"model_extra": {"prompt_tokens_details": {"cached_tokens": 128}}}
        )
        assert client.parse(response).cached_tokens == 128

    def test_cached_tokens_default_to_zero(self, client: Mistral) -> None:
        assert client.parse(_response()).cached_tokens == 0

    def test_handles_a_null_finish_reason(self, client: Mistral) -> None:
        assert client.parse(_response(finish_reason=None)).finish_reason == ""


class _Book(BaseModel):
    title: str


class TestJsonRequest:
    def test_returns_the_validated_model(self, client: Mistral) -> None:
        client.mistral = MagicMock()
        client.mistral.chat.complete.return_value = _response(content='{"title": "X"}')

        data, response = client.json_request("SYS", "USER", _Book)

        assert data.title == "X"
        assert response.model == "mistral-large-latest"
        assert "response_format" in client.mistral.chat.complete.call_args.kwargs

    def test_reasks_on_validation_error(self, client: Mistral) -> None:
        client.mistral = MagicMock()
        client.mistral.chat.complete.side_effect = [
            _response(content='{"wrong": 1}'),
            _response(content='{"title": "corrigé"}'),
        ]

        data, _ = client.json_request("SYS", "USER", _Book, max_retries=2)

        assert data.title == "corrigé"
        assert client.mistral.chat.complete.call_count == 2
        # La conversation de rattrapage reprend la réponse fautive puis la consigne.
        messages = client.mistral.chat.complete.call_args.kwargs["messages"]
        assert messages[2] == {"role": "assistant", "content": '{"wrong": 1}'}
        assert "Validation Error found" in messages[3]["content"]

    def test_raises_after_the_last_attempt(self, client: Mistral) -> None:
        from pydantic import ValidationError

        client.mistral = MagicMock()
        client.mistral.chat.complete.return_value = _response(content='{"wrong": 1}')

        with pytest.raises(ValidationError):
            _ = client.json_request("SYS", "USER", _Book, max_retries=2)

        assert client.mistral.chat.complete.call_count == 2
