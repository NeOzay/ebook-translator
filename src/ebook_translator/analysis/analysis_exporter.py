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

import logging
import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .translation_context import ContexteTraduction, TermeGlossaire

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)

# ------------------------------
# Constantes et configuration
# ------------------------------

MISSING = "—"

# Libellés humains pour clés d'analyse
FIELD_LABELS: dict[str, str] = {
    "resume_narratif": "Résumé narratif",
    "tonalite_ambiance": "Tonalité et ambiance",
    "style_ecriture": "Style d'écriture",
    "themes_images_cles": "Thèmes et images clés",
    "references_culturelles": "Références culturelles",
    "pistes_traduction": "Pistes de traduction",
}

# Ordre stable des sections pour diff déterministe
ANALYSE_ORDER: list[str] = [
    "resume_narratif",
    "tonalite_ambiance",
    "style_ecriture",
    "themes_images_cles",
    "references_culturelles",
    "pistes_traduction",
]


def save_markdown(markdown_content: str, output_path: Path | str) -> None:
    """
    Sauvegarde le contenu Markdown dans un fichier.

    Args:
        markdown_content: Contenu Markdown à sauvegarder
        output_path: Chemin du fichier de sortie

    Example:
        >>> md = export_to_markdown(raw_json)
        >>> save_markdown(md, "cache/analysis/Chapter_1.md")
    """
    output_path = Path(output_path) if isinstance(output_path, str) else output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        f.write(markdown_content)

    logger.info(f"Exporté Markdown: {output_path}")


# ------------------------------
# Helpers internes
# ------------------------------


def _normalize_text(text: str) -> str:
    """
    Nettoie un texte pour rendu Markdown.

    - Supprime espaces en tête/queue
    - Remplace séquences d'espaces par un seul espace

    Args:
        text: Texte d'entrée

    Returns:
        Texte normalisé
    """
    s = text.strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _slugify(label: str) -> str:
    """
    Convertit un label en slug Markdown (ancres H2 compatibles GitHub).

    Args:
        label: Libellé humain

    Returns:
        Slug en minuscules, sans accents, séparé par des tirets
    """
    s = unicodedata.normalize("NFKD", label)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s-]+", "-", s).strip("-")
    return s


def _expand_sexe(code: str) -> str:
    """Convertit le code de sexe en libellé lisible."""
    match code:
        case "m":
            return "Masculin"
        case "f":
            return "Féminin"
        case _:
            return MISSING


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
        p_norm = _normalize_text(p)
        if p_norm:
            items.append(f"- {p_norm}")
    if not items:
        items.append("> Aucune piste fournie.")
    return items


def _escape_table_cell(s: str) -> str:
    """Échappe caractères problématiques pour cellules de table Markdown."""
    s = s.replace("|", "\\|")
    s = s.replace("\n", " ")
    return s


def _format_glossaire_table(entries: list[TermeGlossaire]) -> list[str]:
    """
    Génère la table Markdown du glossaire.

    Colonnes: Terme | Type | Sexe | Rôle | Notes | Proposition
    Tri: par type puis terme (alpha insensible à la casse)

    Args:
        entries: Entrées de glossaire

    Returns:
        Lignes Markdown constituant la table
    """
    if not entries:
        return ["> Aucun terme pertinent identifié."]

    sorted_entries: list[TermeGlossaire] = sorted(
        entries, key=lambda e: (e["type"], e["terme"].lower())
    )

    lines: list[str] = []
    # En-têtes
    lines.append("| Terme | Type | Sexe | Rôle | Notes | Proposition |")
    lines.append("| --- | --- | --- | --- | --- | --- |")

    for e in sorted_entries:
        terme = _escape_table_cell(e.get("terme", MISSING)) or MISSING
        type_ = _escape_table_cell(e.get("type", MISSING)) or MISSING
        sexe = _expand_sexe(e.get("sexe", "nc"))
        role = _escape_table_cell(e.get("description_role", MISSING)) or MISSING
        notes_raw = e.get("notes_traduction", MISSING)
        notes = _escape_table_cell(notes_raw) if notes_raw else MISSING
        proposition_raw = e.get("proposition_traduction", MISSING)
        proposition = (
            _escape_table_cell(proposition_raw) if proposition_raw else MISSING
        )

        # Mise en forme légère: notes en italique, proposition en gras
        notes_fmt = f"_{notes}_" if notes != MISSING else notes
        proposition_fmt = (
            f"**{proposition}**" if proposition != MISSING else proposition
        )

        lines.append(
            f"| {terme} | {type_} | {sexe} | {role} | {notes_fmt} | {proposition_fmt} |"
        )

    return lines


def export_to_markdown(
    analysis: ContexteTraduction,
    toc_threshold: int = 5,
) -> str:
    """
    Transforme une analyse (JSON ContexteTraduction) en Markdown lisible.

    Args:
        raw_analysis: Chaîne JSON de l'analyse
        wrap_width: Largeur de wrapping pour les paragraphes (>0 pour activer)
        toc_threshold: Nombre minimal de sections H2 pour inclure un sommaire

    Returns:
        Document Markdown complet prêt à être sauvegardé

    Raises:
        json.JSONDecodeError: Si le JSON est invalide
        SchemaError: Si le schéma ne respecte pas ContexteTraduction
    """

    lines: list[str] = []

    # Titre H1
    chapitre = _normalize_text(analysis["chapitre"]) or MISSING
    lines.append(f"# {chapitre}\n")

    # Préparation des sections H2
    h2_titles: list[str] = []
    for key in ANALYSE_ORDER:
        label = FIELD_LABELS.get(key, key)
        h2_titles.append(label)
        lines.append(f"## {label}")

        value = analysis["analyse"].get(key)
        if key == "pistes_traduction":
            # Liste à puces
            pistes_lines = _format_pistes(cast(list[str], value))
            lines.extend(pistes_lines)
        else:
            text = _normalize_text(value) if isinstance(value, str) else MISSING
            lines.append(text)

        lines.append("")  # Ligne vide après chaque section

    # Sommaire (optionnel)
    if len(h2_titles) >= toc_threshold:
        toc: list[str] = ["## Sommaire"]
        for title in h2_titles:
            slug = _slugify(title)
            toc.append(f"- [{title}](#{slug})")
        toc.append("")
        # Insérer sommaire après le H1
        # On recompose pour placer le TOC entre H1 et premières sections
        lines = [lines[0], "", *toc, *lines[1:]]

    # Glossaire
    lines.append("## Glossaire")
    gloss_lines = _format_glossaire_table(analysis["glossaire"])
    lines.extend(gloss_lines)
    lines.append("")

    # Fin de document (newline finale)
    return "\n".join(lines).rstrip() + "\n"


class AnalysisExporter:
    """
    Exporte les analyses littéraires au format Markdown.

    Génère des documents Markdown structurés et lisibles pour
    revue manuelle, rapports et documentation.

    Example:
        >>> exporter = AnalysisExporter()
        >>> markdown = exporter.export_to_markdown(analysis)
        >>> exporter.save_markdown(markdown, "Chapter_1.md")
    """

    @staticmethod
    def export(
        analysis: ContexteTraduction,
        output_path: Path | str,
        toc_threshold: int = 5,
    ) -> None:
        """
        Exporte une analyse au format Markdown et sauvegarde dans un fichier.

        Args:
            raw_analysis: Chaîne JSON de l'analyse
            output_path: Chemin du fichier de sortie
            wrap_width: Largeur de wrapping pour les paragraphes
            toc_threshold: Nombre minimal de sections H2 pour inclure un sommaire

        Example:
            >>> exporter = AnalysisExporter()
            >>> exporter.export(raw_json, "cache/analysis/Chapter_1.md")
        """
        markdown = export_to_markdown(analysis, toc_threshold=toc_threshold)
        save_markdown(markdown, output_path)
