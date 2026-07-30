"""
Exporteur Phase 0: Analyse littéraire stratifiée → Markdown lisible.

Ce module transforme une fiche `AnalyseChapter` (schéma Pydantic du
submodule `template`) en document Markdown structuré, destiné à la revue
humaine du cache d'analyse.

Structure Markdown générée:
1. Titre H1 (chapitre)
2. Sommaire (optionnel, au-delà d'un seuil de sections)
3. H2 « Noyau stable » — caractéristiques invariantes du livre
4. H2 « Couche narrative » — état du récit au bloc courant
"""

from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel

from ebook_translator.exporter.helper import normalize_text, save_markdown, slugify
from template.phase.analyze_chapter_layered_models import (
    AnalyseChapter,
    CoucheNarrative,
    NoyauStable,
    SignalCloture,
)

# ------------------------------
# Constantes et configuration
# ------------------------------

MISSING = "—"


def _checked_labels(model: type[BaseModel], labels: dict[str, str]) -> dict[str, str]:
    """Vérifie qu'un dict de libellés recouvre exactement les champs du modèle.

    Garde-fou à l'import : un champ ajouté au schéma sans libellé
    disparaîtrait silencieusement de l'export, un champ supprimé ferait
    lever un `AttributeError` au premier export.

    Args:
        model: Modèle Pydantic dont les champs sont exportés.
        labels: Mapping `nom_de_champ → libellé humain`.

    Returns:
        `labels` inchangé, une fois la correspondance vérifiée.

    Raises:
        ValueError: Si un champ du modèle n'a pas de libellé, ou si un
            libellé vise un champ inexistant.
    """
    fields = set(model.model_fields)
    keys = set(labels)
    if fields != keys:
        raise ValueError(
            f"Libellés d'export désynchronisés de {model.__name__} : "
            f"champs sans libellé {sorted(fields - keys)}, "
            f"libellés sans champ {sorted(keys - fields)}."
        )
    return labels


def _checked_signal_labels(labels: dict[str, str]) -> dict[str, str]:
    """Même garde-fou, pour les valeurs du `Literal` `SignalCloture`.

    Args:
        labels: Mapping `valeur du littéral → libellé humain`.

    Returns:
        `labels` inchangé, une fois la correspondance vérifiée.

    Raises:
        ValueError: Si les clés ne recouvrent pas exactement `SignalCloture`.
    """
    valeurs = set(get_args(SignalCloture))
    if valeurs != set(labels):
        raise ValueError(
            f"Libellés de signal désynchronisés de SignalCloture : "
            f"attendu {sorted(valeurs)}, reçu {sorted(labels)}."
        )
    return labels


# Libellés humains des sections du noyau stable, dans l'ordre d'export.
NOYAU_LABELS: dict[str, str] = _checked_labels(
    NoyauStable,
    {
        "genre_affine": "Genre affiné",
        "registre": "Registre",
        "style_auctorial": "Style auctorial",
        "tonalite_generale": "Tonalité générale",
        "pistes_traduction": "Pistes de traduction",
    },
)

# Libellés humains des sections de la couche narrative, dans l'ordre d'export.
NARRATIVE_LABELS: dict[str, str] = _checked_labels(
    CoucheNarrative,
    {
        "resume_narratif": "Résumé narratif",
        "arcs_en_cours": "Arcs en cours",
        "tensions": "Tensions",
        "themes_emergents": "Thèmes émergents",
        "references_culturelles_rencontrees": "Références culturelles",
    },
)

# Libellés des signaux de clôture d'arc (cf. `SignalCloture`).
SIGNAL_LABELS: dict[str, str] = _checked_signal_labels(
    {
        "aucun": "actif",
        "resolution_explicite": "résolu",
        "ambigu": "ambigu",
    }
)

# Structure racine, dépliée à la main par `export_to_markdown` (un H1 + deux
# H2). Une couche supplémentaire dans le schéma doit faire échouer l'import,
# pas disparaître de l'export.
_ = _checked_labels(
    AnalyseChapter,
    {
        "chapitre": "Chapitre",
        "noyau_stable": "Noyau stable",
        "couche_narrative": "Couche narrative",
    },
)


def _format_bullets(items: list[str]) -> list[str]:
    """
    Formate une liste de chaînes en liste Markdown à puces.

    Args:
        items: Entrées à formater. Les entrées vides sont ignorées.

    Returns:
        Lignes Markdown (une puce par entrée), ou une citation si vide.
    """
    lines: list[str] = []
    for item in items:
        normalized = normalize_text(item)
        if normalized:
            lines.append(f"- {normalized}")
    if not lines:
        lines.append("> Aucune entrée fournie.")
    return lines


def export_to_markdown(
    analysis: AnalyseChapter,
    toc_threshold: int | Literal[False] = 5,
) -> str:
    """
    Transforme une fiche `AnalyseChapter` en Markdown lisible.

    Args:
        analysis: Fiche d'analyse stratifiée du chapitre.
        toc_threshold: Nombre minimal de sections H3 pour inclure un
            sommaire ; `False` désactive le sommaire.

    Returns:
        Document Markdown complet prêt à être sauvegardé.

    Example:
        >>> markdown = export_to_markdown(analyse)
        >>> markdown.startswith("# ")
        True
    """
    lines: list[str] = []
    subsections: list[str] = []

    chapitre = normalize_text(analysis.chapitre) or MISSING
    lines.append(f"# {chapitre}\n")

    noyau = analysis.noyau_stable
    lines.append("## Noyau stable\n")
    for key, label in NOYAU_LABELS.items():
        subsections.append(label)
        lines.append(f"### {label}")
        if key == "pistes_traduction":
            lines.extend(_format_bullets(noyau.pistes_traduction))
        else:
            value: str = getattr(noyau, key)
            lines.append(normalize_text(value) or MISSING)
        lines.append("")

    narrative = analysis.couche_narrative
    lines.append("## Couche narrative\n")
    for key, label in NARRATIVE_LABELS.items():
        subsections.append(label)
        lines.append(f"### {label}")
        if key == "resume_narratif":
            lines.append(normalize_text(narrative.resume_narratif) or MISSING)
        elif key == "arcs_en_cours":
            lines.extend(
                _format_bullets(
                    [
                        f"{arc.arc} "
                        f"({SIGNAL_LABELS.get(arc.signal_cloture, arc.signal_cloture)})"
                        for arc in narrative.arcs_en_cours
                    ]
                )
            )
        else:
            value_list: list[str] = getattr(narrative, key)
            lines.extend(_format_bullets(value_list))
        lines.append("")

    if toc_threshold and len(subsections) >= toc_threshold:
        toc: list[str] = ["## Sommaire"]
        toc.extend(f"- [{title}](#{slugify(title)})" for title in subsections)
        toc.append("")
        # Insérer le sommaire entre le H1 et la première section.
        lines = [lines[0], "", *toc, *lines[1:]]

    return "\n".join(lines).rstrip() + "\n"


class AnalysisExporter:
    """
    Exporte les analyses littéraires au format Markdown.

    Génère des documents Markdown structurés et lisibles pour
    revue manuelle, rapports et documentation.

    Example:
        >>> AnalysisExporter.save_analysis_markdown(analyse, "cache/Chapter_1.md")
    """

    @staticmethod
    def save_analysis_markdown(
        analysis: AnalyseChapter,
        output_path: Path | str,
        toc_threshold: int = 5,
    ) -> None:
        """
        Exporte une analyse au format Markdown et sauvegarde dans un fichier.

        Args:
            analysis: Fiche d'analyse stratifiée du chapitre.
            output_path: Chemin du fichier de sortie.
            toc_threshold: Nombre minimal de sections H3 pour inclure un sommaire.

        Example:
            >>> AnalysisExporter.save_analysis_markdown(analyse, "cache/Chapter_1.md")
        """
        markdown = export_to_markdown(analysis, toc_threshold=toc_threshold)
        save_markdown(markdown, output_path)
