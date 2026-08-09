"""
Résultats d'exécution d'une variante, sérialisables entre les processus.

Chaque variante s'exécute dans un sous-processus (le contexte du pipeline est
un singleton gelé, voir `frozen_static.py`) : le fils écrit son résultat en
JSON, le parent le relit. Ces structures sont le contrat entre les deux.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ebook_translator.llm.usage import PhaseUsage
from ebook_translator.pipeline.context import PhaseStats

type RunStatus = Literal["ok", "partial", "error"]
"""Issue d'une variante, dérivée du travail réellement accompli.

Un statut qui ne dépendait que de l'absence d'exception a laissé passer un run
à `chunks_processed: 0` déclaré réussi, dont le corpus vide est entré dans
l'arbitrage (run de banc vide déclaré réussi, 2026-08-04). Le statut se calcule donc, il ne se déclare pas.
"""

RESULT_FILENAME = "result.json"
"""Nom du fichier de résultat déposé dans le workspace de la variante."""


@dataclass(frozen=True)
class PhaseResult:
    """Mesures d'une phase, extraites de `PhaseStats`.

    Attributes:
        name: Nom de la phase.
        chunks_total: Chunks à traiter.
        chunks_processed: Chunks traités (cache et nouveaux).
        chunks_from_cache: Chunks servis par le cache, sans appel LLM.
        chunks_translated: Chunks nouvellement produits par le LLM.
        chunks_validated: Chunks validés.
        chunks_rejected: Chunks rejetés après validation.
        duration_seconds: Durée de la phase.
        usage: Tokens et appels LLM imputés à la phase.
    """

    name: str
    chunks_total: int = 0
    chunks_processed: int = 0
    chunks_from_cache: int = 0
    chunks_translated: int = 0
    chunks_validated: int = 0
    chunks_rejected: int = 0
    duration_seconds: float = 0.0
    usage: PhaseUsage = field(default_factory=PhaseUsage)

    @classmethod
    def from_stats(cls, stats: PhaseStats) -> PhaseResult:
        """Convertit les statistiques d'une phase en résultat sérialisable.

        Args:
            stats: Statistiques produites par `PhaseExecutor`.

        Returns:
            Résultat équivalent, détaché du pipeline.
        """
        return cls(
            name=str(stats.phase_name),
            chunks_total=stats.chunks_total,
            chunks_processed=stats.chunks_processed,
            chunks_from_cache=stats.chunks_from_cache,
            chunks_translated=stats.chunks_translated,
            chunks_validated=stats.chunks_validated,
            chunks_rejected=stats.chunks_rejected,
            duration_seconds=stats.duration_seconds,
            usage=stats.usage,
        )

    def to_dict(self) -> dict[str, Any]:
        """Représentation JSON de la phase."""
        return {
            "name": self.name,
            "chunks_total": self.chunks_total,
            "chunks_processed": self.chunks_processed,
            "chunks_from_cache": self.chunks_from_cache,
            "chunks_translated": self.chunks_translated,
            "chunks_validated": self.chunks_validated,
            "chunks_rejected": self.chunks_rejected,
            "duration_seconds": round(self.duration_seconds, 3),
            "usage": {
                "llm_calls": self.usage.llm_calls,
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "cached_tokens": self.usage.cached_tokens,
                "reasoning_tokens": self.usage.reasoning_tokens,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhaseResult:
        """Reconstruit une phase depuis sa représentation JSON.

        Args:
            data: Dictionnaire produit par `to_dict`.

        Returns:
            Résultat de phase.
        """
        usage: dict[str, int] = data.get("usage", {})
        return cls(
            name=str(data["name"]),
            chunks_total=int(data.get("chunks_total", 0)),
            chunks_processed=int(data.get("chunks_processed", 0)),
            chunks_from_cache=int(data.get("chunks_from_cache", 0)),
            chunks_translated=int(data.get("chunks_translated", 0)),
            chunks_validated=int(data.get("chunks_validated", 0)),
            chunks_rejected=int(data.get("chunks_rejected", 0)),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            usage=PhaseUsage(
                llm_calls=usage.get("llm_calls", 0),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                cached_tokens=usage.get("cached_tokens", 0),
                reasoning_tokens=usage.get("reasoning_tokens", 0),
            ),
        )


def compute_status(phases: Sequence[PhaseResult]) -> RunStatus:
    """Dérive l'issue d'une variante du travail réellement accompli.

    Seules les phases ayant quelque chose à faire (`chunks_total > 0`) sont
    considérées : une phase sans travail est neutre, pas suspecte. Les chunks
    servis par le cache comptent comme traités — un run entièrement amorcé par
    un `Seed` reste donc `ok`.

    Args:
        phases: Mesures par phase, telles que produites par le pipeline.

    Returns:
        `ok` si chaque phase a traité tout son travail, `partial` s'il en
        manque, `error` si rien n'a été traité du tout.

    Example:
        >>> compute_status([PhaseResult("t", chunks_total=4, chunks_processed=4)])
        'ok'
        >>> compute_status([PhaseResult("t", chunks_total=4, chunks_processed=1)])
        'partial'
        >>> compute_status([PhaseResult("t", chunks_total=4)])
        'error'
    """
    working = [phase for phase in phases if phase.chunks_total > 0]
    if not working:
        return "error"

    if all(phase.chunks_processed == 0 for phase in working):
        return "error"

    if any(phase.chunks_processed < phase.chunks_total for phase in working):
        return "partial"

    return "ok"


def describe_shortfall(phases: Sequence[PhaseResult]) -> str:
    """Résume en une ligne ce qui n'a pas été traité.

    Args:
        phases: Mesures par phase.

    Returns:
        Un texte listant les phases incomplètes, vide si tout a été traité.

    Example:
        >>> describe_shortfall([PhaseResult("t", chunks_total=4, chunks_processed=1)])
        't: 1/4 chunks'
    """
    manquantes = [
        f"{phase.name}: {phase.chunks_processed}/{phase.chunks_total} chunks"
        for phase in phases
        if phase.chunks_total > 0 and phase.chunks_processed < phase.chunks_total
    ]
    return ", ".join(manquantes)


@dataclass(frozen=True)
class VariantResult:
    """Issue d'un run de variante.

    Attributes:
        variant_id: Identifiant de la variante (ou du run d'amorçage).
        status: `ok` si le pipeline est allé au bout, `error` sinon.
        phases: Mesures par phase, dans l'ordre d'exécution.
        duration_seconds: Durée totale du run, mesurée par le fils.
        error: Message d'erreur si `status == "error"`.
        seeded_phases: Phases servies depuis le cache d'amorçage.
    """

    variant_id: str
    status: RunStatus = "ok"
    phases: tuple[PhaseResult, ...] = ()
    duration_seconds: float = 0.0
    error: str | None = None
    seeded_phases: tuple[str, ...] = ()

    @property
    def usage(self) -> PhaseUsage:
        """Consommation cumulée sur toutes les phases."""
        cumul = PhaseUsage()
        for phase in self.phases:
            cumul = cumul + phase.usage
        return cumul

    def phase(self, name: str) -> PhaseResult | None:
        """Mesures d'une phase par nom.

        Args:
            name: Nom de la phase recherchée.

        Returns:
            Le résultat de la phase, ou `None` si elle n'a pas été exécutée.
        """
        for phase in self.phases:
            if phase.name == name:
                return phase
        return None

    def to_dict(self) -> dict[str, Any]:
        """Représentation JSON du résultat."""
        return {
            "variant_id": self.variant_id,
            "status": self.status,
            "duration_seconds": round(self.duration_seconds, 3),
            "error": self.error,
            "seeded_phases": list(self.seeded_phases),
            "phases": [phase.to_dict() for phase in self.phases],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VariantResult:
        """Reconstruit un résultat depuis sa représentation JSON.

        Args:
            data: Dictionnaire produit par `to_dict`.

        Returns:
            Résultat de variante.
        """
        # Tout ce qui n'est pas un statut connu devient `error` : un fichier
        # tronqué ou écrit par une version antérieure ne doit pas se relire en
        # succès. Mais `partial` doit survivre au tour par JSON, sinon une
        # variante dégradée reparaîtrait en échec franc.
        status: RunStatus = "error"
        if data.get("status") == "ok":
            status = "ok"
        elif data.get("status") == "partial":
            status = "partial"

        phases: list[dict[str, Any]] = data.get("phases", [])
        seeded: list[str] = data.get("seeded_phases", [])
        return cls(
            variant_id=str(data["variant_id"]),
            status=status,
            phases=tuple(PhaseResult.from_dict(phase) for phase in phases),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            error=data.get("error"),
            seeded_phases=tuple(seeded),
        )

    def write(self, path: Path) -> None:
        """Écrit le résultat en JSON.

        Args:
            path: Fichier de destination, créé avec ses parents.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def read(cls, path: Path) -> VariantResult:
        """Relit un résultat écrit par `write`.

        Args:
            path: Fichier JSON à relire.

        Returns:
            Résultat de variante.

        Raises:
            FileNotFoundError: Si le fichier n'existe pas.
        """
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)
