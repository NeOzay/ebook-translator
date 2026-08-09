"""Tests de `LLMGlossaryModel` — parsing du format tabulaire délimité."""

from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from ebook_translator.validation.diagnostics import ErreursType
from ebook_translator.validation.failure import from_pydantic_error
from template.phase.glossary_models import (
    GLOSSARY_COLUMNS,
    GLOSSARY_SEPARATOR,
    LLMGlossaryModel,
    LLMTermeGlossary,
)

_NOMINAL = (
    "Alice|personnage|f|Alice\n"
    "White Rabbit|creature|m|Lapin Blanc\n"
    "Dark Army|organisation|nc|Armée des Ténèbres\n"
    "[=[END]=]"
)


class TestParseValid:
    def test_nominal(self):
        entries = LLMGlossaryModel.model_validate(_NOMINAL).build()
        assert entries == [
            {
                "terme": "alice",
                "type": "personnage",
                "sexe": "f",
                "proposition_traduction": "Alice",
            },
            {
                "terme": "white rabbit",
                "type": "creature",
                "sexe": "m",
                "proposition_traduction": "Lapin Blanc",
            },
            {
                "terme": "dark army",
                "type": "organisation",
                "sexe": "nc",
                "proposition_traduction": "Armée des Ténèbres",
            },
        ]

    def test_blank_lines_and_edge_whitespace_ignored(self):
        raw = "  \n  Alice | personnage | f | Alice  \n\n[=[END]=]   \n"
        entries = LLMGlossaryModel.model_validate(raw).build()
        assert entries == [
            {
                "terme": "alice",
                "type": "personnage",
                "sexe": "f",
                "proposition_traduction": "Alice",
            }
        ]

    def test_translation_keeps_its_casing(self):
        """Le terme est normalisé — il sert de clé — mais pas la traduction.

        La casse de la traduction finit dans le texte traduit : un nom propre
        ramené en minuscules y reste en minuscules.
        """
        raw = "dark one|appellation|m|le Ténébreux\n[=[END]=]"
        entry = LLMGlossaryModel.model_validate(raw).build()[0]
        assert entry["terme"] == "dark one"
        assert entry["proposition_traduction"] == "le Ténébreux"

    def test_enum_values_are_case_insensitive(self):
        raw = "Alice|PERSONNAGE|F|Alice\n[=[END]=]"
        entry = LLMGlossaryModel.model_validate(raw).build()[0]
        assert entry["type"] == "personnage"
        assert entry["sexe"] == "f"

    def test_text_after_end_marker_ignored(self):
        raw = "Alice|personnage|f|Alice\n[=[END]=]\nVoilà, j'espère que ça aide !"
        assert len(LLMGlossaryModel.model_validate(raw).build()) == 1

    def test_no_term_is_a_valid_empty_glossary(self):
        """Un bloc sans terme notable ne doit pas faire échouer le chunk."""
        model = LLMGlossaryModel.model_validate("[=[END]=]")
        assert model.build() == []
        assert model.lignes_rejetees == ()

    def test_dict_input_passthrough(self):
        model = LLMGlossaryModel.model_validate(
            {"entrees": [("Alice", "personnage", "f", "Alice")]}
        )
        assert model.build()[0]["terme"] == "alice"

    def test_build_is_a_plain_list_of_typed_dicts(self):
        built = LLMGlossaryModel.model_validate(_NOMINAL).build()
        assert type(built) is list
        assert set(built[0]) == set(GLOSSARY_COLUMNS)


class TestLignesEcartees:
    @pytest.mark.parametrize(
        "ligne",
        [
            pytest.param("Alice|personnage|f", id="trois_colonnes"),
            pytest.param("Alice|personnage|f|Alice|extra", id="cinq_colonnes"),
            pytest.param("Alice|monstre|f|Alice", id="type_inconnu"),
            pytest.param("Alice|personnage|x|Alice", id="sexe_inconnu"),
            pytest.param("|personnage|f|Alice", id="terme_vide"),
            pytest.param("Alice|personnage|f|", id="proposition_vide"),
            pytest.param("terme|type|sexe|proposition_traduction", id="entete"),
            pytest.param('{"entrees": []}', id="json"),
        ],
    )
    def test_ligne_malformee_est_ecartee_sans_perdre_le_reste(self, ligne: str):
        raw = f"{ligne}\nWhite Rabbit|creature|m|Lapin Blanc\n[=[END]=]"
        model = LLMGlossaryModel.model_validate(raw)

        assert [e["terme"] for e in model.build()] == ["white rabbit"]
        assert model.lignes_rejetees == (ligne,)

    @pytest.mark.parametrize(
        "prefixe", ["- ", "* ", "• ", "+ ", "1. ", "2) "], ids=lambda p: repr(p)
    )
    def test_puce_est_nettoyee_plutot_qu_ingeree(self, prefixe: str):
        """Sans ce nettoyage, le glossaire apprendrait un terme `- alice`."""
        model = LLMGlossaryModel.model_validate(
            f"{prefixe}Alice|personnage|f|Alice\n[=[END]=]"
        )
        assert model.build()[0]["terme"] == "alice"
        assert model.lignes_rejetees == ()

    def test_separateur_dans_un_champ_casse_la_cardinalite(self):
        raw = "Ali|ce|personnage|f|Alice\nBob|personnage|m|Bob\n[=[END]=]"
        model = LLMGlossaryModel.model_validate(raw)
        assert [e["terme"] for e in model.build()] == ["bob"]

    def test_rejet_logue_un_warning(self, caplog: pytest.LogCaptureFixture):
        with caplog.at_level(logging.WARNING, logger="template.phase.glossary_models"):
            LLMGlossaryModel.model_validate(
                "Alice|personnage|f\nBob|personnage|m|Bob\n[=[END]=]"
            )
        assert "1 ligne(s) écartée(s) sur 2" in caplog.text


class TestParseErrors:
    def test_missing_end_marker_emits_typed_error(self):
        with pytest.raises(ValidationError) as exc_info:
            LLMGlossaryModel.model_validate("Alice|personnage|f|Alice")

        failures = from_pydantic_error(exc_info.value)
        assert failures[0].error_type is ErreursType.MISSING_END_MARKER
        assert "detail" in failures[0].ctx

    def test_no_usable_line_emits_output_format_invalid(self):
        """Aucune ligne exploitable : le modèle a ignoré le format."""
        raw = '{"colonnes": ["terme"], "entrees": [["Alice"]]}\n[=[END]=]'
        with pytest.raises(ValidationError) as exc_info:
            LLMGlossaryModel.model_validate(raw)

        failures = from_pydantic_error(exc_info.value)
        assert failures[0].error_type is ErreursType.OUTPUT_FORMAT_INVALID
        assert "detail" in failures[0].ctx


class TestRoundTrip:
    def test_serialized_build_reloads_identically(
        self, sample_entries: list[LLMTermeGlossary]
    ):
        """Le cache reste JSON : `build()` doit survivre à un aller-retour."""
        model = LLMGlossaryModel.model_validate(
            {
                "entrees": [
                    (e["terme"], e["type"], e["sexe"], e["proposition_traduction"])
                    for e in sample_entries
                ]
            }
        )
        raw = model.serialized_build()
        assert LLMGlossaryModel.deserialize(raw) == sample_entries


def test_separateur_est_le_pipe():
    """Garde-fou : le prompt et l'exporteur documentent ce séparateur en dur."""
    assert GLOSSARY_SEPARATOR == "|"
