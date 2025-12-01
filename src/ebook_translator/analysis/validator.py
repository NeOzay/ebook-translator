"""
Validation des contextes de traduction (Phase 0).

Valide la structure et le contenu des objets ContexteTraduction.
"""

import re
from typing import Any, cast

from .translation_context import (
    REQUIRED_TERME_FIELDS,
    VALID_GLOSSARY_TYPES,
    VALID_SEXES,
    ContexteTraduction,
    TermeGlossaire,
)


def _validate_and_convert_glossary_entries(
    entrees: list[tuple[str, str, str, str, str, str]], missing_sections: list[str]
) -> list[TermeGlossaire]:
    """
    Convertit le format compact (liste de listes) en liste de dicts.

    Args:
        entrees: Liste de listes, chaque sous-liste contenant exactement 6 valeurs
                 dans l'ordre : [terme, type, sexe, description_role, notes_traduction, proposition_traduction]

    Returns:
        Liste de TermeGlossaire (dicts) avec clés correspondant à l'ordre fixe des colonnes

    Example:
        >>> entrees = [["Alice", "personnage", "f", "Protagoniste", "Conserver", "Alice"]]
        >>> _convert_compact_glossary_to_dicts(entrees)
        [{"terme": "Alice", "type": "personnage", "sexe": "f", ...}]
    """
    glossary_entries: list[TermeGlossaire] = []
    for index, entry in enumerate(entrees):
        if len(entry) != 6:
            missing_sections.append(
                f"glossaire entry {index} does not have exactly 6 elements"
            )
            continue
        if entry[1] not in VALID_GLOSSARY_TYPES:
            missing_sections.append(
                f"glossaire entry {index} has invalid type '{entry[1]}'"
            )
            continue
        if entry[2] not in VALID_SEXES:
            missing_sections.append(
                f"glossaire entry {index} has invalid sexe '{entry[2]}'"
            )
            continue
        glossary_entries.append(
            {
                "terme": entry[0],
                "type": entry[1],
                "sexe": entry[2],
                "description_role": entry[3],
                "notes_traduction": entry[4],
                "proposition_traduction": entry[5],
            }
        )
    return glossary_entries


def _check_glossary_entry(
    glossary_entry: dict[str, Any], missing_sections: list[str], index: int
) -> None:
    # Vérifier champs obligatoires

    for field in REQUIRED_TERME_FIELDS:
        if field not in glossary_entry:
            missing_sections.append(f"glossaire[{index}].{field}")

    # Valider type
    if glossary_entry["type"] not in VALID_GLOSSARY_TYPES:
        missing_sections.append(
            f"glossaire[{index}].type (invalid value '{glossary_entry['type']}', must be one of: {', '.join(VALID_GLOSSARY_TYPES)} )"
        )

    # Valider sexe
    if glossary_entry["sexe"] not in VALID_SEXES:
        missing_sections.append(
            f"glossaire[{index}].sexe (invalid value '{glossary_entry['sexe']}', must be one of: {', '.join(VALID_SEXES)} )"
        )

    # Valider qu'il n'y a qu'UN SEUL terme dans proposition_traduction
    if re.search(r"[\w\s]+(,|/)[\w\s]+", glossary_entry["proposition_traduction"]):
        missing_sections.append(
            f"glossaire[{index}].proposition_traduction must contain exactly ONE term, "
        )

    # Valider que proposition_traduction n'est pas vide
    if not glossary_entry["proposition_traduction"].strip():
        missing_sections.append(
            f"glossaire[{index}].proposition_traduction cannot be empty"
        )


class AnalysisValidator:
    """Valide et vérifie les contextes de traduction."""

    @staticmethod
    def validate(data: dict[str, Any]) -> tuple[ContexteTraduction, list[str]]:
        """
        Valide un contexte JSON contre le schéma ContexteTraduction.

        Args:
            data: Dictionnaire à valider

        Returns:
            Le dictionnaire validé (cast en ContexteTraduction)

        Raises:
            ValueError: Si la validation échoue
        """
        missing_sections: list[str] = []
        # Vérifier présence des champs de premier niveau
        if "chapitre" not in data:
            missing_sections.append("chapitre")
        if "analyse" not in data:
            missing_sections.append("analyse")
        if "glossaire" not in data:
            missing_sections.append("glossaire")

        # Valider structure analyse
        analyse = data["analyse"]
        required_analysis_fields = [
            "resume_narratif",
            "tonalite_ambiance",
            "style_ecriture",
            "themes_images_cles",
            "references_culturelles",
            "pistes_traduction",
        ]
        for field in required_analysis_fields:
            if field not in analyse:
                missing_sections.append(f"analyse.{field}")

        # Valider que pistes_traduction est une liste
        if not isinstance(analyse["pistes_traduction"], list):
            missing_sections.append("analyse.pistes_traduction (must be a list)")
        else:
            # Valider que tous les éléments de pistes_traduction sont des chaînes
            for i, piste in enumerate(analyse["pistes_traduction"]):
                if not isinstance(piste, str):
                    missing_sections.append(
                        f"analyse.pistes_traduction[{i}] (must be a string)"
                    )

        # Valider structure glossaire
        glossaire_raw = data.get("glossaire")
        if isinstance(glossaire_raw, dict):
            # Format compact (liste de listes/tuples)
            glossaire_dict = cast(dict[str, Any], glossaire_raw)
            entries = cast(
                list[tuple[str, str, str, str, str, str]],
                glossaire_dict.get("entrees", []),
            )
            glossaire_list = _validate_and_convert_glossary_entries(
                entries,
                missing_sections,
            )
            data["glossaire"] = glossaire_list
        elif isinstance(glossaire_raw, list):
            glossaire_list = cast(list[Any], glossaire_raw)
            for i, entry in enumerate(glossaire_list):
                if not isinstance(entry, dict):
                    missing_sections.append(f"glossaire[{i}] (must be a dict)")
                    continue
                entry_dict = cast(dict[str, Any], entry)
                _check_glossary_entry(entry_dict, missing_sections, i)
        else:
            missing_sections.append("glossaire (must be a list or dict with 'entrees')")
        return data, missing_sections  # type: ignore
