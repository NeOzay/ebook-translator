"""Non-régression du socle agnostique `LLMClientBase`.

Ces comportements vivaient dans `OpenAIClientBase` avant l'extraction ; ils sont
maintenant partagés par tous les providers, d'où ces tests sur une sous-classe
factice sans SDK.
"""

from enum import StrEnum
from logging import Logger
from typing import Any, Literal, Never, Required, override

import pytest
from pydantic import BaseModel

from ebook_translator.llm.clients.base import LLMClientBase, get_api_key
from ebook_translator.llm.clients.protocol import ClientProviderProtocol
from ebook_translator.llm.llm_config import (
    FullKwargs,
    GenericLLMConfig,
    LLMConfigExport,
    LLMResponse,
    UserKwargs,
)

pytestmark = pytest.mark.llm_module


class FakeModels(StrEnum):
    SMALL = "fake-small"
    BIG = "fake-big"


class UserFakeKwargs(UserKwargs, total=False):
    temperature: float | None
    max_tokens: int | None


class FullFakeKwargs(UserFakeKwargs, FullKwargs, total=False, extra_items=Any):
    model: Required[str]


class FakeClient(
    LLMClientBase[FakeModels, Never, UserFakeKwargs, FullFakeKwargs, dict[str, Any]]
):
    """Provider minimal : enregistre ce qui aurait été envoyé, n'appelle rien."""

    sent: list[FullFakeKwargs]

    @override
    def _build_sdk_client(self, api_key: str) -> None:
        self.api_key = api_key
        self.sent = []

    @override
    def _send(self, params: FullFakeKwargs) -> dict[str, Any]:
        self.sent.append(params)
        return {"content": "ok"}

    @override
    def parse(self, response: dict[str, Any]) -> LLMResponse:
        return LLMResponse(
            content=response["content"],
            reasoning=None,
            tool_calls=None,
            finish_reason="stop",
            prompt_tokens=0,
            completion_tokens=0,
            cached_tokens=0,
            reasoning_tokens=0,
            model="fake",
            response_id="id",
        )

    @override
    def json_request[M: BaseModel](
        self,
        system_prompt: str,
        user_instruction: str,
        response_model: type[M],
        config: Any = None,
        logger: Logger | None = None,
        max_retries: int = 1,
    ) -> tuple[M, LLMResponse]:
        raise NotImplementedError

    @override
    @classmethod
    def _resolve_config(cls, config: Any) -> Any:
        if isinstance(config, LLMConfigExport):
            return config.get_properties(cls)
        if isinstance(config, GenericLLMConfig):
            return {
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
            }
        return config

    @override
    @classmethod
    def get_model_preset_config(
        cls,
        model_strength: Literal["low", "high", "max"] = "high",
        thinking: bool | Literal["low", "high", "max"] = False,
        config: Any = None,
    ) -> LLMConfigExport[FullFakeKwargs]:
        model = FakeModels.BIG if model_strength == "max" else FakeModels.SMALL
        return cls.get_model_config(model, False, config)

    @override
    @classmethod
    def get_model_config(
        cls,
        model_name: FakeModels = FakeModels.SMALL,
        thinking: Any = False,
        config: Any = None,
    ) -> LLMConfigExport[FullFakeKwargs]:
        merged: FullFakeKwargs = {"model": model_name.value}
        if config is not None:
            for k, v in cls._resolve_config(config).items():
                merged[k] = v
        return LLMConfigExport(merged, cls)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "sk-test-not-a-real-key")


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


class TestApiKeyResolution:
    def test_falls_back_to_api_key(self) -> None:
        assert get_api_key(None) == "sk-test-not-a-real-key"

    def test_dedicated_variable_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROVIDER_KEY", "dedicated")
        assert get_api_key("PROVIDER_KEY") == "dedicated"

    def test_explicit_key_skips_the_environment(self) -> None:
        assert FakeClient(api_key="explicit").api_key == "explicit"

    def test_exits_when_no_key_is_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("API_KEY", raising=False)
        with pytest.raises(SystemExit):
            _ = get_api_key("ABSENT_VAR")


class TestConfigMachinery:
    def test_default_config_uses_the_high_preset(self, client: FakeClient) -> None:
        assert client.parameters["model"] == "fake-small"

    def test_set_preset_config_switches_model(self, client: FakeClient) -> None:
        _ = client.set_preset_config("max", False)
        assert client.parameters["model"] == "fake-big"

    def test_set_config_is_chainable(self, client: FakeClient) -> None:
        assert client.set_config(FakeModels.BIG, False) is client

    def test_merge_overwrites_existing_keys(self, client: FakeClient) -> None:
        client.applied_config({"temperature": 0.1})
        client.applied_config({"temperature": 0.9})
        assert client.parameters["temperature"] == 0.9

    def test_none_pops_the_key(self, client: FakeClient) -> None:
        client.applied_config({"temperature": 0.1})
        client.applied_config({"temperature": None})
        assert "temperature" not in client.parameters

    def test_generic_config_is_resolved(self, client: FakeClient) -> None:
        client.applied_config(GenericLLMConfig(temperature=0.4, max_tokens=7))
        assert client.parameters["temperature"] == 0.4
        assert client.parameters["max_tokens"] == 7

    def test_exported_config_rejects_another_provider(self) -> None:
        exported = FakeClient.get_model_preset_config("max", False)
        with pytest.raises(ValueError, match="Provider mismatch"):
            _ = exported.get_properties(str)  # pyright: ignore[reportArgumentType]


class TestRequest:
    def test_injects_the_messages(self, client: FakeClient) -> None:
        _ = client.request("SYS", "USER")
        assert client.sent[0]["messages"] == [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "USER"},
        ]

    def test_returns_the_parsed_response(self, client: FakeClient) -> None:
        assert client.request("SYS", "USER").content == "ok"

    def test_per_call_config_does_not_leak(self, client: FakeClient) -> None:
        _ = client.request("SYS", "USER", config={"temperature": 0.5})
        assert client.sent[0]["temperature"] == 0.5
        assert "temperature" not in client.parameters

    def test_satisfies_provider_protocol(self, client: FakeClient) -> None:
        assert isinstance(client, ClientProviderProtocol)


class TestLogging:
    def test_writes_header_prompt_and_response(
        self, client: FakeClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        logger = logging.getLogger("test.exchange")
        with caplog.at_level(logging.INFO, logger="test.exchange"):
            _ = client.request("SYS", "USER", logger=logger)

        written = "\n".join(caplog.messages)
        assert "LLM REQUEST LOG" in written
        assert "=== MESSAGES ===" in written
        assert "SYS" in written and "USER" in written
        assert "=== RESPONSE ===" in written

    def test_header_omits_the_messages(
        self, client: FakeClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        logger = logging.getLogger("test.exchange")
        with caplog.at_level(logging.INFO, logger="test.exchange"):
            client.write_header(logger, None, {"model": "m", "messages": ["secret"]})

        assert "secret" not in caplog.messages[0]
        assert "Model     : m" in caplog.messages[0]
