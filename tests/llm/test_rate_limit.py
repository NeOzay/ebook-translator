"""Limiteur de débit : espacement entre threads, entre processus, et AIMD.

Le défaut d'origine (run de banc vide du 2026-08-04) est une rafale d'appels simultanés absorbée en
429 puis perdue en silence. Les deux tests qui portent ce module sont donc
`test_threads_are_spaced_out` et `test_two_processes_share_the_slot` : ils
reproduisent les deux formes de concurrence que le pipeline crée réellement —
les threads d'executor et de validation d'un côté, les sous-processus de
variantes du banc de l'autre.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from ebook_translator.llm.rate_limit import (
    MAX_DEGRADATION,
    RECOVERY_STREAK,
    RateLimiter,
    provider_key_for,
)

pytestmark = pytest.mark.llm_module


def _limiter(tmp_path: Path, per_minute: int = 600) -> RateLimiter:
    """Limiteur isolé : 600/min = 100 ms d'espacement, mesurable sans lenteur."""
    return RateLimiter(per_minute, provider_key="essai", state_dir=tmp_path)


class TestConstruction:
    @pytest.mark.parametrize("per_minute", [0, -1, -60])
    def test_non_positive_rate_is_rejected(
        self, per_minute: int, tmp_path: Path
    ) -> None:
        # Un plafond mal réglé doit se voir, pas passer en illimité.
        with pytest.raises(ValueError, match="strictement positif"):
            _ = RateLimiter(per_minute, provider_key="essai", state_dir=tmp_path)

    def test_interval_derives_from_the_rate(self, tmp_path: Path) -> None:
        assert _limiter(tmp_path, per_minute=60).interval == pytest.approx(1.0)

    def test_state_file_is_named_after_the_provider(self, tmp_path: Path) -> None:
        limiter = RateLimiter(30, provider_key="Mistral/v1", state_dir=tmp_path)

        assert limiter.state_path.parent == tmp_path
        assert limiter.state_path.name == "mistral_v1"


class TestSpacing:
    def test_first_acquire_is_immediate(self, tmp_path: Path) -> None:
        limiter = _limiter(tmp_path)

        start = time.monotonic()
        limiter.acquire()

        assert time.monotonic() - start < 0.05

    def test_successive_acquires_are_spaced(self, tmp_path: Path) -> None:
        limiter = _limiter(tmp_path, per_minute=600)  # 100 ms

        limiter.acquire()
        start = time.monotonic()
        limiter.acquire()

        assert time.monotonic() - start >= 0.09

    def test_threads_are_spaced_out(self, tmp_path: Path) -> None:
        """8 threads concurrents — au-delà de tout `worker_count` réaliste.

        C'est le test central : l'executor et le pool de validation émettent
        ensemble, et un limiteur à jetons accumulables les relâcherait en même
        temps.
        """
        limiter = _limiter(tmp_path, per_minute=600)  # 100 ms
        departures: list[float] = []
        guard = threading.Lock()
        ready = threading.Barrier(8)

        def worker() -> None:
            _ = ready.wait()
            limiter.acquire()
            with guard:
                departures.append(time.monotonic())

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(departures) == 8
        departures.sort()
        intervals = [
            b - a for a, b in zip(departures[:-1], departures[1:], strict=True)
        ]
        # Aucune paire ne doit repartir ensemble : c'est la rafale qu'on interdit.
        assert min(intervals) >= 0.08, f"départs en rafale : {intervals}"
        # Et l'espacement ne doit pas dériver : 7 intervalles de ~100 ms.
        assert departures[-1] - departures[0] >= 0.6

    def test_two_processes_share_the_slot(self, tmp_path: Path) -> None:
        """Deux processus se partagent le créneau via le fichier verrouillé.

        C'est le cas du banc : chaque variante est un sous-processus, donc un
        limiteur en mémoire seule repartirait à zéro à chaque variante.
        """
        script = (
            "import sys, time\n"
            "from pathlib import Path\n"
            "from ebook_translator.llm.rate_limit import RateLimiter\n"
            "limiter = RateLimiter(60, provider_key='essai', "
            "state_dir=Path(sys.argv[1]))\n"
            "limiter.acquire()\n"
            "print(time.time())\n"
        )

        # Le premier réserve le créneau ; le second doit attendre ~1 s.
        first = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        start = time.time()
        second = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        waited = float(second.stdout.strip()) - float(first.stdout.strip())

        assert waited >= 0.9, f"le second processus n'a pas attendu ({waited:.2f}s)"
        assert time.time() - start >= 0.9


class TestAimd:
    def test_penalize_halves_the_rate(self, tmp_path: Path) -> None:
        limiter = _limiter(tmp_path, per_minute=600)
        before = limiter.current_rate

        limiter.penalize()

        assert limiter.current_rate == pytest.approx(before / 2)

    def test_rate_never_falls_below_the_floor(self, tmp_path: Path) -> None:
        limiter = _limiter(tmp_path, per_minute=600)
        nominal = limiter.current_rate

        for _ in range(20):
            limiter.penalize()

        assert limiter.current_rate == pytest.approx(nominal / MAX_DEGRADATION)

    def test_retry_after_pushes_the_shared_slot(self, tmp_path: Path) -> None:
        limiter = _limiter(tmp_path, per_minute=600)

        limiter.penalize(retry_after=1.5)
        deadline = float(limiter.state_path.read_text(encoding="utf-8"))

        # Le délai annoncé protège aussi les autres threads et processus.
        assert deadline - time.time() >= 1.4

    def test_successes_restore_the_rate_by_steps(self, tmp_path: Path) -> None:
        limiter = _limiter(tmp_path, per_minute=600)
        limiter.penalize()
        degraded = limiter.current_rate

        for _ in range(RECOVERY_STREAK):
            limiter.record_success()

        assert limiter.current_rate > degraded

    def test_partial_streak_changes_nothing(self, tmp_path: Path) -> None:
        limiter = _limiter(tmp_path, per_minute=600)
        limiter.penalize()
        degraded = limiter.current_rate

        for _ in range(RECOVERY_STREAK - 1):
            limiter.record_success()

        assert limiter.current_rate == pytest.approx(degraded)

    def test_recovery_stops_at_the_nominal_rate(self, tmp_path: Path) -> None:
        limiter = _limiter(tmp_path, per_minute=600)
        nominal = limiter.current_rate
        limiter.penalize()

        for _ in range(RECOVERY_STREAK * 40):
            limiter.record_success()

        assert limiter.current_rate == pytest.approx(nominal)

    def test_penalize_resets_the_streak(self, tmp_path: Path) -> None:
        limiter = _limiter(tmp_path, per_minute=600)
        limiter.penalize()
        for _ in range(RECOVERY_STREAK - 1):
            limiter.record_success()

        limiter.penalize()
        degraded = limiter.current_rate
        limiter.record_success()

        assert limiter.current_rate == pytest.approx(degraded)


class TestProviderKey:
    def test_declared_key_wins(self) -> None:
        class Client:
            provider_key = "mistral"

        assert provider_key_for(Client()) == "mistral"

    def test_falls_back_on_the_class_name(self) -> None:
        class Deepseek: ...

        assert provider_key_for(Deepseek()) == "Deepseek"

    def test_none_falls_back_on_the_class_name(self) -> None:
        # C'est le défaut porté par `LLMClientBase`.
        class Client:
            provider_key = None

        assert provider_key_for(Client()) == "Client"


class TestResilience:
    """Le fichier partagé peut manquer : le limiteur dégrade, il ne rend pas les armes.

    Ces tests couvrent ce que le `flock` ne peut plus assurer quand le fichier
    est indisponible. Ils ne prouvent **pas** la nécessité du `threading.Lock` :
    vérifié par mutation, le neutraliser ne fait échouer aucun test, la fenêtre
    de course entre lecture et écriture de `_local_deadline` étant trop étroite
    pour être déclenchée de façon reproductible. Le verrou reste requis pour
    l'intégrité de l'état mutable partagé (`_rate`, `_successes`,
    `_local_deadline`) ; c'est un invariant, pas une propriété observable.
    """

    @staticmethod
    def _break_state_file(monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_args: object, **_kwargs: object) -> None:
            # Court délai : simule la latence d'une E/S qui échoue et relâche le
            # GIL, sans consommer la marge des mesures d'espacement.
            time.sleep(0.002)
            raise OSError("système de fichiers en lecture seule")

        monkeypatch.setattr(Path, "open", boom)

    def test_unwritable_state_dir_degrades_without_failing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        limiter = _limiter(tmp_path)
        self._break_state_file(monkeypatch)

        # Une traduction ne doit pas échouer parce que le cache est indisponible.
        limiter.acquire()

    def test_spacing_survives_an_unavailable_state_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        limiter = _limiter(tmp_path, per_minute=600)  # 100 ms
        self._break_state_file(monkeypatch)

        limiter.acquire()
        start = time.monotonic()
        limiter.acquire()

        # Sans échéance locale, la panne du fichier rendrait le limiteur inerte.
        assert time.monotonic() - start >= 0.09

    def test_threads_stay_spaced_without_the_shared_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        limiter = _limiter(tmp_path, per_minute=600)  # 100 ms
        self._break_state_file(monkeypatch)

        departures: list[float] = []
        guard = threading.Lock()
        ready = threading.Barrier(4)

        def worker() -> None:
            _ = ready.wait()
            limiter.acquire()
            with guard:
                departures.append(time.monotonic())

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        departures.sort()
        intervals = [
            b - a for a, b in zip(departures[:-1], departures[1:], strict=True)
        ]
        assert min(intervals) >= 0.08, f"départs en rafale : {intervals}"
