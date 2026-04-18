import json
import re
from functools import cache
from typing import Any, cast

from ebook_translator.validator.translation_context import (
    REQUIRED_TERME_FIELDS,
    TermeGlossaire,
)


def _validate_and_convert_glossary_entries(
    entrees: list[tuple[str, ...]],
    missing_sections: list[str],
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
    size = 4
    glossary_entries: list[TermeGlossaire] = []
    for index, entry in enumerate(entrees):
        if len(entry) != size:
            missing_sections.append(
                f"glossaire entry {index} does not have exactly {size} elements"
            )
            continue
        # if entry[1] not in VALID_GLOSSARY_TYPES:
        #     missing_sections.append(
        #         f"glossaire entry {index} has invalid type '{entry[1]}'"
        #     )
        #     continue
        # if entry[2] not in VALID_SEXES:
        #     missing_sections.append(
        #         f"glossaire entry {index} has invalid sexe '{entry[2]}'"
        #     )
        #     continue
        glossary_entries.append(
            {
                "terme": entry[0],
                "type": entry[1],
                "sexe": entry[2],
                # "description_role": entry[3],
                # "notes_traduction": entry[4],
                "proposition_traduction": entry[3],
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

    # # Valider type
    # if glossary_entry["type"] not in VALID_GLOSSARY_TYPES:
    #     missing_sections.append(
    #         f"glossaire[{index}].type (invalid value '{glossary_entry['type']}', must be one of: {', '.join(VALID_GLOSSARY_TYPES)} )"
    #     )
    #
    # # Valider sexe
    # if glossary_entry["sexe"] not in VALID_SEXES:
    #     missing_sections.append(
    #         f"glossaire[{index}].sexe (invalid value '{glossary_entry['sexe']}', must be one of: {', '.join(VALID_SEXES)} )"
    #     )

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


class GlossaryValidator:
    @staticmethod
    @cache
    def load(data: str) -> list[TermeGlossaire]:
        raw_data = json.loads(data)
        validated_data, missing_sections = GlossaryValidator.validate(raw_data)
        if missing_sections:
            raise ValueError(
                f"ContexteTraduction validation failed, missing or invalid sections: {', '.join(missing_sections)}"
            )
        return validated_data

    @staticmethod
    def validate(data: dict[str, Any]) -> tuple[list[TermeGlossaire], list[str]]:
        missing_sections: list[str] = []
        glossaire_list: list[Any] = []

        if "glossaire" not in data and isinstance(data, list):
            glossaire_list = cast(list[Any], data)
            for i, entry in enumerate(glossaire_list):
                if not isinstance(entry, dict):
                    continue
                entry_dict = cast(dict[str, Any], entry)
                _check_glossary_entry(entry_dict, missing_sections, i)
        else:
            # Valider structure glossaire
            glossaire_raw = data.get("glossaire")
            if isinstance(glossaire_raw, dict):  # LLM output format with "entrees" key
                # Format compact (liste de listes/tuples)
                glossaire_dict = cast(dict[str, Any], glossaire_raw)
                entries = cast(
                    list[tuple[str, ...]],
                    glossaire_dict.get("entrees", []),
                )
                glossaire_list = _validate_and_convert_glossary_entries(
                    entries,
                    missing_sections,
                )
                data["glossaire"] = glossaire_list
            else:
                missing_sections.append(
                    "glossaire (must be a list or dict with 'entrees')"
                )

        return glossaire_list, missing_sections
