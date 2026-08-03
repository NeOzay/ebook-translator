"""Tests de l'accumulateur de consommation LLM (`llm/usage.py`)."""

import threading

import pytest

from ebook_translator.llm.llm_config import LLMResponse
from ebook_translator.llm.usage import UNATTRIBUTED, PhaseUsage, UsageMeter


def make_response(
    prompt: int = 100,
    completion: int = 40,
    cached: int = 10,
    reasoning: int = 5,
) -> LLMResponse:
    """Construit une `LLMResponse` minimale portant les compteurs voulus."""
    return LLMResponse(
        content="ok",
        reasoning=None,
        tool_calls=None,
        finish_reason="stop",
        prompt_tokens=prompt,
        completion_tokens=completion,
        cached_tokens=cached,
        reasoning_tokens=reasoning,
        model="test-model",
        response_id="resp-1",
    )


class TestPhaseUsage:
    def test_addition_terme_a_terme(self):
        somme = PhaseUsage(1, 100, 40, 10, 5) + PhaseUsage(2, 200, 60, 0, 1)

        assert somme == PhaseUsage(3, 300, 100, 10, 6)

    def test_total_tokens_exclut_les_sous_ensembles(self):
        # cached et reasoning sont des parts de prompt/completion, pas des
        # suppléments : les additionner compterait deux fois.
        usage = PhaseUsage(1, 100, 40, cached_tokens=90, reasoning_tokens=30)

        assert usage.total_tokens == 140


class TestUsageMeter:
    def test_impute_a_la_phase_courante(self):
        meter = UsageMeter()
        meter.current_phase = "initial"

        meter.record(make_response())

        assert meter.for_phase("initial") == PhaseUsage(1, 100, 40, 10, 5)
        assert meter.for_phase("refined") == PhaseUsage()

    def test_sans_phase_courante_impute_hors_phase(self):
        meter = UsageMeter()

        meter.record(make_response())

        assert meter.for_phase(UNATTRIBUTED).llm_calls == 1

    def test_cumule_les_appels_successifs(self):
        meter = UsageMeter()
        meter.current_phase = "initial"

        meter.record(make_response())
        meter.record(make_response(prompt=50, completion=20, cached=0, reasoning=0))

        assert meter.for_phase("initial") == PhaseUsage(2, 150, 60, 10, 5)

    def test_total_agrege_toutes_les_phases(self):
        meter = UsageMeter()
        meter.current_phase = "initial"
        meter.record(make_response())
        meter.current_phase = "refined"
        meter.record(make_response())

        assert meter.total() == PhaseUsage(2, 200, 80, 20, 10)

    def test_snapshot_est_detache(self):
        meter = UsageMeter()
        meter.current_phase = "initial"
        meter.record(make_response())

        snapshot = meter.snapshot()
        meter.record(make_response())

        assert snapshot["initial"].llm_calls == 1
        assert meter.for_phase("initial").llm_calls == 2

    def test_delta_since_isole_le_passage_courant(self):
        meter = UsageMeter()
        meter.current_phase = "initial"
        meter.record(make_response())

        baseline = meter.for_phase("initial")
        meter.record(make_response(prompt=10, completion=5, cached=0, reasoning=0))

        assert meter.delta_since(baseline, "initial") == PhaseUsage(1, 10, 5, 0, 0)

    def test_reset_vide_compteurs_et_phase(self):
        meter = UsageMeter()
        meter.current_phase = "initial"
        meter.record(make_response())

        meter.reset()

        assert meter.total() == PhaseUsage()
        assert meter.current_phase is None

    @pytest.mark.parametrize("nb_threads", [8])
    def test_enregistrement_concurrent(self, nb_threads: int):
        meter = UsageMeter()
        meter.current_phase = "initial"
        appels_par_thread = 50

        def worker() -> None:
            for _ in range(appels_par_thread):
                meter.record(
                    make_response(prompt=1, completion=1, cached=0, reasoning=0)
                )

        threads = [threading.Thread(target=worker) for _ in range(nb_threads)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        attendu = nb_threads * appels_par_thread
        assert meter.for_phase("initial") == PhaseUsage(attendu, attendu, attendu, 0, 0)
