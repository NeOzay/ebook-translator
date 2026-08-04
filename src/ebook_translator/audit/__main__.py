"""
Ligne de commande de l'audit de phase.

    uv run python -m ebook_translator.audit <cache_dir> --phase glossary

Mesure la sortie d'une phase dans un cache existant et écrit le répertoire
d'audit. Aucun appel LLM : la matière est déjà sur le disque. Le verdict se
demande ensuite avec `/phase-audit`.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from ebook_translator.audit.auditor import audited_phases, get_auditor
from ebook_translator.audit.findings import AuditFindings
from ebook_translator.audit.report import DEFAULT_AUDITS_DIR, write_audit
from ebook_translator.audit.source import AuditSource, AuditSourceError
from ebook_translator.cli import program_name
from ebook_translator.logger import get_logger
from ebook_translator.pipeline.base import PhaseName

logger = get_logger(__name__)


MODULE_INVOCATION = "python -m ebook_translator.audit"
"""Forme longue, à afficher quand la commande est lancée par `-m`."""


def main(argv: list[str] | None = None) -> int:
    """Audite une phase et écrit son rapport.

    Args:
        argv: Arguments de ligne de commande (par défaut `sys.argv[1:]`).

    Returns:
        Code de sortie : 0 si l'audit a abouti, 1 sinon.
    """
    parser = argparse.ArgumentParser(
        prog=program_name(MODULE_INVOCATION),
        description="Audite une phase du pipeline contre son cahier des charges.",
    )
    _ = parser.add_argument(
        "cache_dir",
        type=Path,
        help="Cache d'un run (`.<stem>_cache/` ou `bench/runs/<id>/work/<v>/cache/`)",
    )
    _ = parser.add_argument(
        "--phase",
        default=str(PhaseName.GLOSSARY),
        choices=[str(phase) for phase in audited_phases()],
        help="Phase à auditer",
    )
    _ = parser.add_argument(
        "--epub",
        type=Path,
        default=None,
        help="EPUB source (déduit du répertoire parent du cache par défaut)",
    )
    _ = parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=f"Répertoire de sortie (défaut : {DEFAULT_AUDITS_DIR}/<horodatage>-<phase>)",
    )
    args = parser.parse_args(argv)

    cache_dir: Path = args.cache_dir
    phase = PhaseName(args.phase)
    epub_path: Path | None = args.epub
    output_dir: Path | None = args.out

    try:
        source = AuditSource.resolve(cache_dir, epub_path)
        auditor = get_auditor(phase)
        findings = auditor.run(source)
    except (AuditSourceError, KeyError) as erreur:
        logger.error(f"❌ Audit impossible : {erreur}")
        print(f"Audit impossible : {erreur}", file=sys.stderr)
        return 1

    destination = output_dir or _default_output_dir(phase)
    _ = write_audit(findings, source, destination)

    _report_to_console(findings, destination)
    return 0


def _report_to_console(findings: AuditFindings, destination: Path) -> None:
    """Résume l'audit sur la sortie standard.

    Le logger console est réglé sur `ERROR` : sans ces `print`, la commande
    n'écrirait rien du tout et le chemin de son propre résultat resterait à
    deviner.

    Args:
        findings: Constats de l'auditeur.
        destination: Répertoire d'audit écrit.
    """
    print(f"Audit « {findings.phase} » écrit dans {destination}")
    print(f"  {len(findings.metrics)} métrique(s) — voir {destination / 'metrics.md'}")

    observations = findings.ranked_observations()
    if not observations:
        print("  aucune catégorie d'écart mesurée")
    else:
        print(f"  {len(observations)} catégorie(s) d'écart :")
        for observation in observations:
            print(f"    {observation.count:>5}  {observation.category}")

    for note in findings.notes:
        print(f"  ! {_flatten(note)}")
    print(f"Verdict : /phase-audit sur {destination}")


def _flatten(note: str) -> str:
    """Ramène une note à une seule ligne de terminal.

    Args:
        note: Note du rapport, en Markdown.

    Returns:
        La note sans saut de ligne ni emphase.
    """
    return " ".join(note.replace("**", "").split())


def _default_output_dir(phase: PhaseName) -> Path:
    """Répertoire de sortie par défaut, horodaté.

    Args:
        phase: Phase auditée.

    Returns:
        Un chemin sous `DEFAULT_AUDITS_DIR`.
    """
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_AUDITS_DIR / f"{horodatage}-{str(phase).replace(' ', '-')}"


if __name__ == "__main__":
    raise SystemExit(main())
