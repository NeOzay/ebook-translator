"""Traduction des erreurs du SDK Mistral vers la taxonomie de `llm/errors.py`.

Sans cette traduction, les erreurs Mistral tomberaient dans le `except Exception`
final de `LLM.query` : ni backoff exponentiel, ni traitement du rate limit.
"""

from unittest.mock import MagicMock

import httpx
import pytest
from mistralai.client.errors import SDKError

from ebook_translator.llm.clients.mistral import (
    Mistral,
    _translate_error,  # pyright: ignore[reportPrivateUsage]
)
from ebook_translator.llm.errors import (
    LLMAPIError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from ebook_translator.llm.llm import LLM

pytestmark = pytest.mark.llm_module


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "sk-test-not-a-real-key")


def _sdk_error(status_code: int) -> SDKError:
    request = httpx.Request("POST", "https://api.mistral.ai/v1/chat/completions")
    response = httpx.Response(status_code, text="boom", request=request)
    return SDKError("échec", response)


class TestTranslateError:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (429, LLMRateLimitError),
            (408, LLMTimeoutError),
            (504, LLMTimeoutError),
            (500, LLMAPIError),
            (400, LLMAPIError),
        ],
    )
    def test_maps_http_status_codes(
        self, status_code: int, expected: type[Exception]
    ) -> None:
        assert isinstance(_translate_error(_sdk_error(status_code)), expected)

    def test_maps_httpx_timeout(self) -> None:
        assert isinstance(
            _translate_error(httpx.TimeoutException("timed out")), LLMTimeoutError
        )

    def test_maps_other_httpx_errors(self) -> None:
        assert isinstance(_translate_error(httpx.ConnectError("refused")), LLMAPIError)

    def test_leaves_unrelated_errors_untouched(self) -> None:
        original = ValueError("sans rapport")
        assert _translate_error(original) is original


class TestSendTranslatesErrors:
    def test_send_raises_the_normalized_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        client = Mistral()
        client.mistral = MagicMock()
        client.mistral.chat.complete.side_effect = _sdk_error(429)

        with pytest.raises(LLMRateLimitError):
            _ = client.request("SYS", "USER")


class TestLLMRetriesOnNormalizedErrors:
    """`LLM.query` doit rejouer une erreur normalisée comme une erreur openai."""

    def test_rate_limit_is_retried_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("time.sleep", lambda _: None)

        response = MagicMock()
        response.content = "ok"

        client = MagicMock()
        client.parameters = {"model": "mistral-large-latest"}
        client.request.side_effect = [LLMRateLimitError("429"), response]

        llm = LLM(client=client, max_retries=3, retry_delay=0.0)

        assert llm.query("SYS", "USER") == "ok"
        assert client.request.call_count == 2

    def test_timeout_is_retried_then_reraised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("time.sleep", lambda _: None)

        client = MagicMock()
        client.parameters = {"model": "mistral-large-latest"}
        client.request.side_effect = LLMTimeoutError("timeout")

        llm = LLM(client=client, max_retries=2, retry_delay=0.0)

        with pytest.raises(LLMTimeoutError):
            _ = llm.query("SYS", "USER")
        assert client.request.call_count == 2
