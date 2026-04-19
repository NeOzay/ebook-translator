"""
Exporteur Phase 0: Analyse littéraire → Markdown lisible.

Ce module transforme une fiche d'analyse JSON (schéma ContexteTraduction)
en document Markdown structuré et lisible pour la revue humaine.

Sorties supportées:
- JSON (source, non modifié) : parsing programmatique en amont
- Markdown (cible) : titres H1/H2, listes, table glossaire

Structure Markdown générée:
1. Titre H1 (chapitre)
2. Sommaire (optionnel)
3. Sections H2 pour l'analyse littéraire (6 clés)
    - Résumé narratif
    - Tonalité et ambiance
    - Style d'écriture
    - Thèmes et images clés
    - Références culturelles
    - Pistes de traduction (liste à puces)
4. Glossaire (table Markdown triée)
5. Métadonnées (version schéma)
"""

from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from ebook_translator.exporter.helper import normalize_text, save_markdown, slugify
from ebook_translator.validator.translation_context import ContexteTraduction

if TYPE_CHECKING:
    from template.types import AnalyseLitteraireKey


# ------------------------------
# Constantes et configuration
# ------------------------------

MISSING = "—"

# Libellés humains pour clés d'analyse
FIELD_LABELS: dict[AnalyseLitteraireKey, str] = {
    "resume_narratif": "Résumé narratif",
    "tonalite_ambiance": "Tonalité et ambiance",
    "style_ecriture": "Style d'écriture",
    "themes_images_cles": "Thèmes et images clés",
    "references_culturelles": "Références culturelles",
    "pistes_traduction": "Pistes de traduction",
}

# Ordre stable des sections pour diff déterministe
ANALYSE_ORDER: tuple[AnalyseLitteraireKey, ...] = tuple(FIELD_LABELS.keys())


def _format_pistes(pistes: list[str]) -> list[str]:
    """
    Formate les pistes de traduction en liste à puces.

    Args:
        pistes: Liste de pistes

    Returns:
        Lignes Markdown (chaque piste en puce)
    """
    items: list[str] = []
    for p in pistes:
        p_norm = normalize_text(p)
        if p_norm:
            items.append(f"- {p_norm}")
    if not items:
        items.append("> Aucune piste fournie.")
    return items


def export_to_markdown(
    analysis: ContexteTraduction,
    toc_threshold: int | Literal[False] = 5,
    # append_glossary: bool = True,
) -> str:
    """
    Transforme une analyse (JSON ContexteTraduction) en Markdown lisible.

    Args:
        raw_analysis: Chaîne JSON de l'analyse
        toc_threshold: Nombre minimal de sections H2 pour inclure un sommaire, set à False pour désactiver

    Returns:
        Document Markdown complet prêt à être sauvegardé

    Raises:
        json.JSONDecodeError: Si le JSON est invalide
        SchemaError: Si le schéma ne respecte pas ContexteTraduction
    """

    lines: list[str] = []

    # Titre H1
    chapitre = normalize_text(analysis["chapitre"]) or MISSING
    lines.append(f"# {chapitre}\n")

    # Préparation des sections H2
    h2_titles: list[str] = []
    for key in ANALYSE_ORDER:
        label = FIELD_LABELS.get(key, key)
        h2_titles.append(label)
        lines.append(f"## {label}")

        value = analysis["analyse"][key]
        if key == "pistes_traduction":
            # Liste à puces
            pistes_lines = _format_pistes(cast(list[str], value))
            lines.extend(pistes_lines)
        else:
            text = normalize_text(value) if isinstance(value, str) else MISSING
            lines.append(text)

        lines.append("")  # Ligne vide après chaque section

    # Sommaire (optionnel)
    if toc_threshold and len(h2_titles) >= toc_threshold:
        toc: list[str] = ["## Sommaire"]
        for title in h2_titles:
            slug = slugify(title)
            toc.append(f"- [{title}](#{slug})")
        toc.append("")
        # Insérer sommaire après le H1
        # On recompose pour placer le TOC entre H1 et premières sections
        lines = [lines[0], "", *toc, *lines[1:]]

    # Glossaire
    # if append_glossary:
    #     lines.append("## Glossaire")
    #     gloss_lines = _format_glossaire_table(analysis["glossaire"])
    #     lines.extend(gloss_lines)
    #     lines.append("")

    # Fin de document (newline finale)
    return "\n".join(lines).rstrip() + "\n"


class AnalysisExporter:
    """
    Exporte les analyses littéraires au format Markdown.

    Génère des documents Markdown structurés et lisibles pour
    revue manuelle, rapports et documentation.

    Example:
        >>> AnalysisExporter.export(analysis, "cache/analysis/Chapter_1.md")
    """

    @staticmethod
    def save_analysis_markdown(
        analysis: ContexteTraduction,
        output_path: Path | str,
        toc_threshold: int = 5,
    ) -> None:
        """
        Exporte une analyse au format Markdown et sauvegarde dans un fichier.

        Args:
            analysis: Chaîne JSON de l'analyse
            output_path: Chemin du fichier de sortie
            toc_threshold: Nombre minimal de sections H2 pour inclure un sommaire

        Example:
            >>> AnalysisExporter.export(analysis, "cache/analysis/Chapter_1.md")
        """
        markdown = export_to_markdown(analysis, toc_threshold=toc_threshold)
        save_markdown(markdown, output_path)
