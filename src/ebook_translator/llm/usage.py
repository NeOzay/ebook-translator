"""
Comptabilité des tokens consommés par les requêtes LLM.

`LLMResponse` porte déjà les compteurs renvoyés par le provider
(`prompt_tokens`, `completion_tokens`, `cached_tokens`, `reasoning_tokens`)
mais ils étaient jusqu'ici jetés à la sortie de `LLM.query`. Ce module les
agrège par phase, pour alimenter `PhaseStats` et le banc d'essais comparatif.

L'attribution repose sur `UsageMeter.current_phase`, posé par `PhaseExecutor`
au début de chaque phase : les phases s'exécutent l'une après l'autre et les
corrections demandées par les workers de validation restent dans la phase
courante (`wait_completion` clôt la phase), donc tous les threads actifs à un
instant donné appartiennent à la même phase.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ebook_translator.llm.llm_config import LLMResponse

UNATTRIBUTED = "<hors-phase>"
"""Clé d'imputation des requêtes émises alors qu'aucune phase n'est active."""


@dataclass(frozen=True)
class PhaseUsage:
    """Tokens et appels cumulés sur une phase.

    Attributes:
        llm_calls: Nombre de réponses LLM reçues (les retries API ayant échoué
            ne comptent pas : seule une réponse aboutie est enregistrée).
        prompt_tokens: Tokens d'entrée facturés, cache inclus.
        completion_tokens: Tokens produits par le modèle.
        cached_tokens: Part de `prompt_tokens` servie depuis le cache du
            provider (sous-ensemble, pas un supplément).
        reasoning_tokens: Part de `completion_tokens` consommée par le
            raisonnement, quand le modèle en expose le détail.
    """

    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0

    def __add__(self, other: PhaseUsage) -> PhaseUsage:
        """Somme terme à terme de deux relevés.

        Args:
            other: Relevé à additionner.

        Returns:
            Nouveau relevé cumulé.
        """
        return PhaseUsage(
            llm_calls=self.llm_calls + other.llm_calls,
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )

    @property
    def total_tokens(self) -> int:
        """Tokens facturés au total (entrée + sortie)."""
        return self.prompt_tokens + self.completion_tokens


@dataclass
class UsageMeter:
    """Accumulateur thread-safe des relevés de consommation, indexé par phase.

    Example:
        >>> meter = UsageMeter()
        >>> meter.current_phase = "initial"
        >>> meter.record(response)  # doctest: +SKIP
        >>> meter.for_phase("initial").llm_calls  # doctest: +SKIP
        1
    """

    current_phase: str | None = None
    """Phase à laquelle imputer les prochaines requêtes. `None` → `UNATTRIBUTED`."""

    _by_phase: dict[str, PhaseUsage] = field(default_factory=dict[str, PhaseUsage])
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, response: LLMResponse) -> None:
        """Impute une réponse LLM à la phase courante.

        Args:
            response: Réponse renvoyée par le provider.
        """
        phase = self.current_phase or UNATTRIBUTED
        entry = PhaseUsage(
            llm_calls=1,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            cached_tokens=response.cached_tokens,
            reasoning_tokens=response.reasoning_tokens,
        )
        with self._lock:
            self._by_phase[phase] = self._by_phase.get(phase, PhaseUsage()) + entry

    def for_phase(self, phase: str) -> PhaseUsage:
        """Relevé cumulé d'une phase.

        Args:
            phase: Nom de la phase.

        Returns:
            Relevé de la phase, ou un relevé vide si elle n'a rien consommé.
        """
        with self._lock:
            return self._by_phase.get(phase, PhaseUsage())

    def total(self) -> PhaseUsage:
        """Relevé cumulé sur toutes les phases.

        Returns:
            Somme de tous les relevés enregistrés.
        """
        with self._lock:
            entries = list(self._by_phase.values())
        cumul = PhaseUsage()
        for entry in entries:
            cumul = cumul + entry
        return cumul

    def snapshot(self) -> dict[str, PhaseUsage]:
        """Copie des relevés par phase.

        Returns:
            Mapping `nom de phase → relevé`, détaché de l'accumulateur.
        """
        with self._lock:
            return dict(self._by_phase)

    def reset(self) -> None:
        """Remet tous les compteurs à zéro et oublie la phase courante."""
        with self._lock:
            self._by_phase.clear()
        self.current_phase = None

    def delta_since(self, baseline: PhaseUsage, phase: str) -> PhaseUsage:
        """Consommation d'une phase depuis un relevé de référence.

        Utile quand une même phase est traversée plusieurs fois : le meter
        cumule, alors que `PhaseStats` veut la part du passage courant.

        Args:
            baseline: Relevé pris avant le passage.
            phase: Nom de la phase mesurée.

        Returns:
            Différence terme à terme entre le relevé courant et `baseline`.
        """
        current = self.for_phase(phase)
        return replace(
            current,
            llm_calls=current.llm_calls - baseline.llm_calls,
            prompt_tokens=current.prompt_tokens - baseline.prompt_tokens,
            completion_tokens=current.completion_tokens - baseline.completion_tokens,
            cached_tokens=current.cached_tokens - baseline.cached_tokens,
            reasoning_tokens=current.reasoning_tokens - baseline.reasoning_tokens,
        )
