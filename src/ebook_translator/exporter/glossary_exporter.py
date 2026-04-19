from pathlib import Path

from template.types import LLMTermeGlossaire

from ebook_translator.exporter.helper import save_markdown

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


def _format_glossaire_table(entries: list[LLMTermeGlossaire]) -> list[str]:
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

    sorted_entries: list[LLMTermeGlossaire] = sorted(
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


class GlossaryExporter:
    @staticmethod
    def save_glossary_markdown(
        glossary: list[LLMTermeGlossaire],
        output_path: Path | str,
    ) -> None:
        text = "\n".join(_format_glossaire_table(glossary))
        save_markdown(text, output_path)
