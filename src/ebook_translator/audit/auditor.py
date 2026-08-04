"""
Protocole d'auditeur de phase et registre des auditeurs disponibles.

Un auditeur ne connaît qu'une phase et sait produire ses constats à partir d'un
`AuditSource`. Le socle — résolution de source, rapport, agent — ne connaît que
ce protocole : ajouter l'audit d'une phase revient à écrire une classe et à
l'enregistrer ici, sans toucher au reste.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ebook_translator.audit.findings import AuditFindings
from ebook_translator.audit.source import AuditSource
from ebook_translator.pipeline.base import PhaseName


@runtime_checkable
class PhaseAuditor(Protocol):
    """Auditeur d'une phase, contre son cahier des charges."""

    @property
    def phase(self) -> PhaseName:
        """Phase auditée."""
        ...

    @property
    def spec_name(self) -> str:
        """Nom du cahier des charges dans `audit/specs/`, sans extension."""
        ...

    def run(self, source: AuditSource) -> AuditFindings:
        """Mesure la sortie de la phase dans un cache.

        Args:
            source: Cache à auditer.

        Returns:
            Les constats : métriques, catalogue d'erreurs, limites de mesure.
        """
        ...


def get_auditor(phase: PhaseName) -> PhaseAuditor:
    """Auditeur enregistré pour une phase.

    L'import est différé pour éviter un cycle : les auditeurs concrets importent
    `findings` et `source`, que ce module expose déjà.

    Args:
        phase: Phase à auditer.

    Returns:
        L'auditeur correspondant.

    Raises:
        KeyError: Si aucun auditeur n'est écrit pour cette phase.
    """
    from ebook_translator.audit.glossary_auditor import GlossaryAuditor

    auditeurs: dict[PhaseName, PhaseAuditor] = {
        PhaseName.GLOSSARY: GlossaryAuditor(),
    }

    if phase not in auditeurs:
        disponibles = ", ".join(str(nom) for nom in auditeurs)
        raise KeyError(
            f"Aucun auditeur pour la phase « {phase} ». Disponibles : {disponibles}"
        )
    return auditeurs[phase]


def audited_phases() -> tuple[PhaseName, ...]:
    """Phases pour lesquelles un auditeur existe.

    Returns:
        Les phases auditables.
    """
    return (PhaseName.GLOSSARY,)
