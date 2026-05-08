from pathlib import Path
from typing import TYPE_CHECKING

from ebook_translator.exporter.helper import save_markdown

if TYPE_CHECKING:
    from template.phase.glossary_models import LLMTermeGlossary

MISSING = "—"


def _expand_sexe(code: str) -> str:
    """Convertit le code de sexe en libellé lisible."""
    match code:
        case "m":
            return "Masculin"
        case "f":
            return "Féminin"
        case _:
            return MISSING


def _escape_table_cell(s: str) -> str:
    """Échappe caractères problématiques pour cellules de table Markdown."""
    s = s.replace("|", "\\|")
    s = s.replace("\n", " ")
    return s


def _format_glossaire_table(entries: list[LLMTermeGlossary]) -> list[str]:
    """
    Génère la table Markdown du glossaire.

    Colonnes: Terme | Type | Sexe | Proposition
    Tri: par type puis terme (alpha insensible à la casse)

    Args:
        entries: Entrées de glossaire

    Returns:
        Lignes Markdown constituant la table
    """
    if not entries:
        return ["> Aucun terme pertinent identifié."]

    sorted_entries: list[LLMTermeGlossary] = sorted(
        entries, key=lambda e: (e["type"], e["terme"])
    )

    lines: list[str] = []
    lines.append("| Terme | Type | Sexe | Proposition |")
    lines.append("| --- | --- | --- | --- |")

    for e in sorted_entries:
        terme = _escape_table_cell(e["terme"]) or MISSING
        type_ = _escape_table_cell(e["type"]) or MISSING
        sexe = _expand_sexe(e["sexe"])
        proposition = _escape_table_cell(e["proposition_traduction"]) or MISSING
        proposition_fmt = (
            f"**{proposition}**" if proposition != MISSING else proposition
        )

        lines.append(f"| {terme} | {type_} | {sexe} | {proposition_fmt} |")

    return lines


class GlossaryExporter:
    @staticmethod
    def save_glossary_markdown(
        glossary: list[LLMTermeGlossary],
        output_path: Path | str,
    ) -> None:
        text = "\n".join(_format_glossaire_table(glossary))
        save_markdown(text, output_path)
