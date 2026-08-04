"""
Rendu d'un audit : rapport lisible, métriques et cahier des charges.

Le répertoire produit est destiné à un agent qui démarre à contexte vide. Il
porte donc tout ce qui permet de conclure sans rien connaître du run : la spec de
la phase (recopiée, pas référencée — l'agent ne doit pas avoir à la chercher), les
chiffres, et le catalogue d'erreurs avec ses exemples.

Le catalogue est classé par effectif décroissant. C'est délibéré : l'objet de
l'audit est de faire remonter les erreurs *les plus fréquentes* d'une phase, celles
qui valent un ajustement de prompt, pas de dresser un inventaire à plat.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from ebook_translator.audit.findings import AuditFindings, Observation
from ebook_translator.audit.source import AuditSource
from ebook_translator.exporter.helper import save_markdown
from ebook_translator.logger import get_logger

logger = get_logger(__name__)

DEFAULT_AUDITS_DIR = Path("audit/runs")
"""Répertoire des audits, à la racine du dépôt."""

REPORT_NAME = "report.md"
METRICS_NAME = "metrics.md"
SPEC_NAME = "spec.md"
MANIFEST_NAME = "manifest.json"
VERDICT_NAME = "verdict.md"

SPECS_DIR = Path(__file__).parent / "specs"
"""Cahiers des charges livrés avec le package."""


def write_audit(
    findings: AuditFindings,
    source: AuditSource,
    output_dir: Path,
) -> Path:
    """Écrit le répertoire d'audit.

    Args:
        findings: Constats de l'auditeur.
        source: Cache audité, pour le manifeste.
        output_dir: Répertoire de sortie, créé au besoin.

    Returns:
        Le répertoire écrit.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    save_markdown(_render_report(findings), output_dir / REPORT_NAME)
    save_markdown(_render_metrics(findings), output_dir / METRICS_NAME)
    save_markdown(_read_spec(findings.spec_name), output_dir / SPEC_NAME)
    _write_manifest(findings, source, output_dir / MANIFEST_NAME)

    logger.info(f"📋 Audit écrit dans {output_dir}")
    return output_dir


def _read_spec(spec_name: str) -> str:
    """Charge le cahier des charges d'une phase.

    Args:
        spec_name: Nom du fichier dans `specs/`, sans extension.

    Returns:
        Le Markdown de la spec, ou un avertissement si elle manque.
    """
    chemin = SPECS_DIR / f"{spec_name}.md"
    if not chemin.is_file():
        logger.warning(f"Cahier des charges introuvable : {chemin}")
        return (
            f"# Cahier des charges manquant\n\n"
            f"Aucun fichier `specs/{spec_name}.md` dans le package. L'audit ne peut "
            f"être jugé que sur ses chiffres.\n"
        )
    return chemin.read_text(encoding="utf-8")


def _render_report(findings: AuditFindings) -> str:
    """Compose le rapport principal.

    Args:
        findings: Constats de l'auditeur.

    Returns:
        Le Markdown du rapport.
    """
    lignes: list[str] = [
        f"# Audit — phase « {findings.phase} »",
        "",
        "Constats mesurés sur le cache d'un run, sans appel LLM. **Aucun seuil**",
        "n'est appliqué : les chiffres décrivent, ils ne jugent pas. La référence est",
        f"le cahier des charges de la phase, recopié dans `{SPEC_NAME}`.",
        "",
        "## Chiffres",
        "",
    ]
    lignes.extend(_metrics_table(findings))
    lignes.extend(
        [
            "",
            "## Catalogue d'erreurs",
            "",
            "Classé par effectif décroissant. Chaque catégorie porte ses exemples ;",
            "les catégories fondées sur une heuristique contiennent des faux positifs",
            "par construction — voir la description de chacune. Une catégorie",
            "d'effectif nul reste affichée : le signal a été cherché et non trouvé.",
            "Les catégories qu'un audit n'a pas pu mesurer sont listées en",
            "« Limites de mesure ».",
            "",
        ]
    )

    observations = findings.ranked_observations()
    if not observations:
        lignes.append("> Aucun écart relevé.")
    else:
        lignes.extend(_observations_summary(observations))
        for observation in observations:
            lignes.extend(_observation_section(observation))

    if findings.notes:
        lignes.extend(["", "## Limites de mesure", ""])
        lignes.extend(f"- {note}" for note in findings.notes)

    return "\n".join(lignes) + "\n"


def _metrics_table(findings: AuditFindings) -> list[str]:
    """Table des métriques.

    Args:
        findings: Constats de l'auditeur.

    Returns:
        Les lignes Markdown de la table.
    """
    if not findings.metrics:
        return ["> Aucune métrique."]

    lignes = ["| Métrique | Valeur | Précision |", "| --- | --- | --- |"]
    lignes.extend(
        f"| {metric.label} | {metric.rendered_value()} | {metric.detail or '—'} |"
        for metric in findings.metrics
    )
    return lignes


def _observations_summary(observations: Sequence[Observation]) -> list[str]:
    """Table de synthèse du catalogue d'erreurs.

    Args:
        observations: Observations déjà classées.

    Returns:
        Les lignes Markdown de la table, suivies d'une ligne vide.
    """
    lignes = ["| Catégorie | Effectif | Objet |", "| --- | --- | --- |"]
    lignes.extend(
        f"| `{obs.category}` | {obs.count} | {obs.title} |" for obs in observations
    )
    lignes.append("")
    return lignes


def _observation_section(observation: Observation) -> list[str]:
    """Section détaillée d'une observation.

    Args:
        observation: Observation à rendre.

    Returns:
        Les lignes Markdown de la section.
    """
    lignes = [
        "",
        f"### `{observation.category}` — {observation.title} ({observation.count})",
        "",
        observation.description,
        "",
    ]

    if not observation.samples:
        lignes.append(
            "> Aucun cas relevé."
            if observation.count == 0
            else "> Aucun exemple retenu."
        )
        return lignes

    lignes.extend(["| Cas | Observé | Contexte |", "| --- | --- | --- |"])
    lignes.extend(
        f"| {_cell(sample.subject)} | {_cell(sample.evidence)} "
        f"| {_cell(sample.context) or '—'} |"
        for sample in observation.samples
    )

    # Les cas au-delà des exemples sont nommés, pas seulement comptés : sans eux,
    # le lecteur ne peut pas trier les faux positifs de la catégorie.
    reste = observation.undetailed_subjects()
    if reste:
        lignes.extend(
            ["", f"_Autres cas ({len(reste)}), sans détail :_ " + ", ".join(reste)]
        )
    elif observation.count > len(observation.samples):
        lignes.extend(
            ["", f"_… et {observation.count - len(observation.samples)} autre(s) cas._"]
        )
    return lignes


def _render_metrics(findings: AuditFindings) -> str:
    """Compose le fichier de métriques seules.

    Args:
        findings: Constats de l'auditeur.

    Returns:
        Le Markdown des métriques.
    """
    lignes = [f"# Métriques — phase « {findings.phase} »", ""]
    lignes.extend(_metrics_table(findings))
    return "\n".join(lignes) + "\n"


def _write_manifest(findings: AuditFindings, source: AuditSource, path: Path) -> None:
    """Écrit le manifeste de l'audit.

    Args:
        findings: Constats de l'auditeur.
        source: Cache audité.
        path: Fichier de sortie.
    """
    manifeste = {
        "phase": str(findings.phase),
        "spec": findings.spec_name,
        "cache_dir": str(source.cache_dir),
        "epub": str(source.epub_path) if source.epub_path else None,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "metrics": {m.label: m.value for m in findings.metrics},
        "observations": {o.category: o.count for o in findings.ranked_observations()},
    }
    _ = path.write_text(
        json.dumps(manifeste, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _cell(text: str) -> str:
    """Échappe un texte pour une cellule de table Markdown.

    Args:
        text: Texte brut.

    Returns:
        Le texte sans pipe ni saut de ligne.
    """
    return text.replace("|", "\\|").replace("\n", " ").strip()
