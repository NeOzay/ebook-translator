"""Traitement des 429 par `LLM` : budget en temps, `Retry-After`, limiteur.

Avant ce chantier, un 429 consommait une tentative de `max_retries` et attendait
`retry_delay * 3**attempt` : 4 secondes au total avant d'abandonner le chunk.
Aucune limite exprimée par minute ne pouvait être franchie — c'est ce qui
produisait des runs de banc vides déclarés réussis (run de banc vide déclaré réussi, 2026-08-04).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ebook_translator.llm.errors import LLMRateLimitError
from ebook_translator.llm.llm import LLM, MAX_RATE_LIMIT_HITS
from ebook_translator.llm.rate_limit import RateLimiter

pytestmark = pytest.mark.llm_module


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Capture les durées d'attente au lieu de les subir."""
    durations: list[float] = []

    def fake_sleep(seconds: float) -> None:
        durations.append(seconds)

    monkeypatch.setattr("time.sleep", fake_sleep)
    return durations


def _client(*side_effect: object) -> MagicMock:
    client = MagicMock()
    client.parameters = {"model": "essai"}
    client.request.side_effect = list(side_effect)
    return client


def _response(content: str = "ok") -> MagicMock:
    response = MagicMock()
    response.content = content
    return response


class TestBudgetSeparateFromMaxRetries:
    def test_rate_limits_do_not_consume_network_attempts(
        self, slept: list[float]
    ) -> None:
        # 5 rejets puis un succès, avec max_retries=2 : l'ancienne boucle
        # abandonnait à la deuxième tentative.
        client = _client(
            *[LLMRateLimitError("429") for _ in range(5)],
            _response(),
        )
        llm = LLM(client=client, max_retries=2, retry_delay=1.0)

        assert llm.query("SYS", "USER") == "ok"
        assert client.request.call_count == 6

    def test_network_errors_still_consume_attempts(self, slept: list[float]) -> None:
        from ebook_translator.llm.errors import LLMTimeoutError

        client = _client(*[LLMTimeoutError("timeout") for _ in range(5)])
        llm = LLM(client=client, max_retries=2, retry_delay=0.0)

        with pytest.raises(LLMTimeoutError):
            _ = llm.query("SYS", "USER")
        assert client.request.call_count == 2

    def test_exhausted_budget_raises_the_rate_limit_error(
        self, slept: list[float]
    ) -> None:
        client = _client(*[LLMRateLimitError("429") for _ in range(50)])
        llm = LLM(client=client, max_retries=3, retry_delay=1.0, rate_limit_budget=10.0)

        with pytest.raises(LLMRateLimitError):
            _ = llm.query("SYS", "USER")

        assert sum(slept) <= 10.0

    def test_budget_allows_far_more_than_four_seconds(self, slept: list[float]) -> None:
        client = _client(*[LLMRateLimitError("429") for _ in range(50)])
        llm = LLM(
            client=client, max_retries=3, retry_delay=1.0, rate_limit_budget=120.0
        )

        with pytest.raises(LLMRateLimitError):
            _ = llm.query("SYS", "USER")

        # Le défaut d'origine : 4 s au total. On doit désormais tenir bien plus.
        assert sum(slept) > 60.0

    def test_zero_delay_cannot_loop_forever(self, slept: list[float]) -> None:
        # Un provider qui annonce `Retry-After: 0` ne consomme aucun budget.
        client = _client(
            *[LLMRateLimitError("429", retry_after=0.0) for _ in range(200)]
        )
        llm = LLM(client=client, max_retries=3, retry_delay=1.0)

        with pytest.raises(LLMRateLimitError):
            _ = llm.query("SYS", "USER")

        assert client.request.call_count == MAX_RATE_LIMIT_HITS


class TestRetryAfterIsHonored:
    def test_announced_delay_wins_over_backoff(self, slept: list[float]) -> None:
        client = _client(LLMRateLimitError("429", retry_after=47.0), _response())
        llm = LLM(client=client, max_retries=3, retry_delay=1.0)

        _ = llm.query("SYS", "USER")

        assert slept == [47.0]

    def test_backoff_is_used_without_an_announced_delay(
        self, slept: list[float]
    ) -> None:
        client = _client(
            LLMRateLimitError("429"), LLMRateLimitError("429"), _response()
        )
        llm = LLM(client=client, max_retries=3, retry_delay=1.0)

        _ = llm.query("SYS", "USER")

        assert slept == [1.0, 3.0]


class TestLimiterIsDriven:
    @staticmethod
    def _limiter(tmp_path: Path) -> MagicMock:
        limiter = MagicMock(spec=RateLimiter)
        # `penalize` rend la pause qu'il a imposée au créneau partagé : c'est
        # elle que `query` décompte du budget, au lieu de dormir lui-même.
        limiter.penalize.return_value = 28.6
        return limiter

    def test_slot_is_taken_before_every_attempt(
        self, slept: list[float], tmp_path: Path
    ) -> None:
        limiter = self._limiter(tmp_path)
        client = _client(LLMRateLimitError("429"), _response())
        llm = LLM(client=client, max_retries=3, retry_delay=0.0, rate_limiter=limiter)

        _ = llm.query("SYS", "USER")

        # Un retry après 429 doit reprendre un créneau, pas repartir aussitôt.
        assert limiter.acquire.call_count == 2

    def test_rate_limit_penalizes_with_the_announced_delay(
        self, slept: list[float], tmp_path: Path
    ) -> None:
        limiter = self._limiter(tmp_path)
        client = _client(LLMRateLimitError("429", retry_after=12.0), _response())
        llm = LLM(client=client, max_retries=3, retry_delay=0.0, rate_limiter=limiter)

        _ = llm.query("SYS", "USER")

        limiter.penalize.assert_called_once_with(12.0)

    def test_no_double_wait_when_the_limiter_holds_the_slot(
        self, slept: list[float], tmp_path: Path
    ) -> None:
        """Avec un limiteur, `query` ne dort pas : `acquire()` tient l'attente.

        Constaté sur le run réel `debit_b` (2026-08-09) : le limiteur repoussait
        le créneau de 28,6 s et le journal annonçait « Attente de 1.0s ». Le
        comportement était correct, la trace mensongère — et une trace
        mensongère est ce qui avait égaré le chantier `glossaire-precision`.
        """
        limiter = self._limiter(tmp_path)
        client = _client(LLMRateLimitError("429"), _response())
        llm = LLM(client=client, max_retries=3, retry_delay=1.0, rate_limiter=limiter)

        _ = llm.query("SYS", "USER")

        assert slept == [], "attente comptée deux fois : sleep + créneau"

    def test_budget_counts_the_pause_imposed_by_the_limiter(
        self, slept: list[float], tmp_path: Path
    ) -> None:
        limiter = self._limiter(tmp_path)  # penalize rend 28.6 s
        client = _client(*[LLMRateLimitError("429") for _ in range(50)])
        llm = LLM(
            client=client,
            max_retries=3,
            retry_delay=1.0,
            rate_limiter=limiter,
            rate_limit_budget=60.0,
        )

        with pytest.raises(LLMRateLimitError):
            _ = llm.query("SYS", "USER")

        # 28,6 × 2 tient dans 60 s, la troisième pause déborde.
        assert client.request.call_count == 3

    def test_success_is_recorded(self, slept: list[float], tmp_path: Path) -> None:
        limiter = self._limiter(tmp_path)
        llm = LLM(
            client=_client(_response()),
            max_retries=3,
            retry_delay=0.0,
            rate_limiter=limiter,
        )

        _ = llm.query("SYS", "USER")

        limiter.record_success.assert_called_once()

    def test_no_limiter_keeps_the_previous_behaviour(self, slept: list[float]) -> None:
        llm = LLM(client=_client(_response()), max_retries=3, retry_delay=0.0)

        assert llm.query("SYS", "USER") == "ok"


class TestJsonQuery:
    """La voie Instructor doit tenir le même budget que `query`."""

    @staticmethod
    def _json_client(*side_effect: object) -> MagicMock:
        client = MagicMock()
        client.parameters = {"model": "essai"}
        client.json_request.side_effect = list(side_effect)
        return client

    def test_rate_limit_is_absorbed_then_the_call_succeeds(
        self, slept: list[float]
    ) -> None:
        payload = MagicMock()
        client = self._json_client(
            LLMRateLimitError("429", retry_after=5.0),
            (payload, MagicMock()),
        )
        llm = LLM(client=client, max_retries=3, retry_delay=1.0)

        result: Any = llm.json_query("SYS", "USER", MagicMock())

        assert result is payload
        assert slept == [5.0]
        assert client.json_request.call_count == 2

    def test_exhausted_budget_raises(self, slept: list[float]) -> None:
        client = self._json_client(
            *[LLMRateLimitError("429") for _ in range(50)],
        )
        llm = LLM(client=client, max_retries=3, retry_delay=1.0, rate_limit_budget=5.0)

        with pytest.raises(LLMRateLimitError):
            _ = llm.json_query("SYS", "USER", MagicMock())

    def test_slot_is_taken_before_every_attempt(self, slept: list[float]) -> None:
        limiter = MagicMock(spec=RateLimiter)
        limiter.penalize.return_value = 28.6
        client = self._json_client(LLMRateLimitError("429"), (MagicMock(), MagicMock()))
        llm = LLM(client=client, max_retries=3, retry_delay=0.0, rate_limiter=limiter)

        _ = llm.json_query("SYS", "USER", MagicMock())

        assert limiter.acquire.call_count == 2
        limiter.record_success.assert_called_once()
