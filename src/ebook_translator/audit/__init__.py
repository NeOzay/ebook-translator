"""
Audit d'une phase du pipeline contre son cahier des charges.

Là où `ebook_translator.bench` compare N variantes entre elles, l'audit vérifie
qu'une phase fait *son* travail — deux variantes également mauvaises se
départagent quand même sur un banc comparatif.

Le procédé tient en deux temps : des **métriques déterministes** mesurées sur le
cache d'un run, sans appel LLM ni seuil GO/NO-GO ; puis un **agent auditeur** qui
lit ces constats en regard du cahier des charges de la phase
(`audit/specs/<phase>.md`) et tranche ce que le chiffre ne capte pas.

    uv run python -m ebook_translator.audit <cache_dir> --phase glossary
"""

from ebook_translator.audit.auditor import PhaseAuditor, audited_phases, get_auditor
from ebook_translator.audit.findings import (
    AuditFindings,
    Metric,
    Observation,
    Sample,
)
from ebook_translator.audit.source import AuditSource, AuditSourceError

__all__ = [
    "AuditFindings",
    "AuditSource",
    "AuditSourceError",
    "Metric",
    "Observation",
    "PhaseAuditor",
    "Sample",
    "audited_phases",
    "get_auditor",
]
