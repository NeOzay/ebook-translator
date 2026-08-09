"""Extraction du `Retry-After` annoncé par un provider.

Un backoff aveugle ne peut pas franchir une limite exprimée par minute : le
délai annoncé par le provider est la seule information fiable dont dispose le
pipeline. Il était jusqu'ici jeté par `_translate_error`.
"""

from datetime import UTC, datetime

import httpx
import pytest
from mistralai.client.errors import SDKError

from ebook_translator.llm.clients.mistral import (
    _translate_error,  # pyright: ignore[reportPrivateUsage]
)
from ebook_translator.llm.errors import LLMRateLimitError, retry_after_seconds

pytestmark = pytest.mark.llm_module


class TestRetryAfterSeconds:
    def test_reads_delta_seconds(self) -> None:
        assert retry_after_seconds({"retry-after": "30"}) == 30.0

    def test_reads_canonical_casing(self) -> None:
        assert retry_after_seconds({"Retry-After": "12"}) == 12.0

    def test_reads_http_date(self) -> None:
        now = datetime(2015, 10, 21, 7, 27, 0, tzinfo=UTC)
        headers = {"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"}

        assert retry_after_seconds(headers, now=now) == 60.0

    def test_past_http_date_yields_zero_not_negative(self) -> None:
        now = datetime(2015, 10, 21, 8, 0, 0, tzinfo=UTC)
        headers = {"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"}

        assert retry_after_seconds(headers, now=now) == 0.0

    def test_negative_delta_is_clamped(self) -> None:
        assert retry_after_seconds({"retry-after": "-5"}) == 0.0

    @pytest.mark.parametrize(
        "headers",
        [
            None,
            {},
            {"retry-after": ""},
            {"retry-after": "   "},
            {"retry-after": "n'importe quoi"},
        ],
    )
    def test_absent_or_unreadable_yields_none(
        self, headers: dict[str, str] | None
    ) -> None:
        assert retry_after_seconds(headers) is None

    def test_reads_httpx_headers_case_insensitively(self) -> None:
        # C'est la forme réellement reçue des deux SDK.
        headers = httpx.Headers({"RETRY-AFTER": "45"})

        assert retry_after_seconds(headers) == 45.0


class TestTranslateErrorCarriesRetryAfter:
    @staticmethod
    def _sdk_error(status_code: int, headers: dict[str, str] | None = None) -> SDKError:
        request = httpx.Request("POST", "https://api.mistral.ai/v1/chat/completions")
        response = httpx.Response(
            status_code, text="boom", request=request, headers=headers
        )
        return SDKError("échec", response)

    def test_429_carries_the_announced_delay(self) -> None:
        error = _translate_error(self._sdk_error(429, {"retry-after": "47"}))

        assert isinstance(error, LLMRateLimitError)
        assert error.retry_after == 47.0

    def test_429_without_header_carries_none(self) -> None:
        error = _translate_error(self._sdk_error(429))

        assert isinstance(error, LLMRateLimitError)
        assert error.retry_after is None
