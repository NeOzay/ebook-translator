"""
Schéma Pydantic de la sortie LLM de la phase d'analyse littéraire stratifiée.

Source de vérité unique de la structure JSON produite par le LLM. Consommé par
l'orchestrateur via Instructor en `Mode.TOOLS_STRICT`. Les contraintes
exprimables en types Python vivent ici ; le prompt
(`analyze_chapter_layered_system.jinja`) ne décrit plus la structure.

Un seul modèle pour les trois modes (`bootstrap`, `seed`, `incremental`) :
la structure JSON est identique, seules les règles de mise à jour diffèrent
(elles restent dans le prompt). Le drapeau `is_last_block` reste également
hors schéma — il déclenche des consignes de clôture, pas un changement de
structure.

Les snapshots échangés entre l'orchestrateur et le LLM (entrée
`existing_analysis`, entrée `previous_chapter_analysis`) sont sérialisés
depuis `AnalyseChapter` via `model_dump_json()`.
"""

from typing import Literal, override

from pydantic import BaseModel, ConfigDict, Field, field_validator

from template.types import ConvertibleModel

SignalCloture = Literal["aucun", "resolution_explicite", "ambigu"]

PISTES_TRADUCTION_MAX: int = 15


def _aucun_element_vide(valeurs: list[str]) -> list[str]:
    for index, valeur in enumerate(valeurs):
        if not valeur or not valeur.strip():
            raise ValueError(
                f"L'élément à la position {index} est vide. Toute entrée "
                f"doit être une chaîne non vide."
            )
    return valeurs


class Arc(BaseModel):
    """Arc narratif suivi sur le chapitre courant."""

    model_config = ConfigDict(extra="forbid")

    arc: str = Field(
        min_length=1,
        description="Description courte de l'arc narratif suivi.",
    )
    signal_cloture: SignalCloture = Field(
        description=(
            "État de clôture de l'arc à ce point du récit. "
            "`aucun` = arc actif, rien ne signale de fermeture. "
            "`resolution_explicite` = scène de résolution dans le texte lu. "
            "`ambigu` = signaux contradictoires, fin laissée ouverte."
        ),
    )


class NoyauStable(BaseModel):
    """Caractéristiques invariantes du livre, évoluent lentement."""

    model_config = ConfigDict(extra="forbid")

    genre_affine: str = Field(
        min_length=1,
        description=(
            "Libellé court et précis du genre, ex. 'thriller psychologique', "
            "'fantasy épique'. Doit pouvoir remplacer `genre` dans la phrase "
            "'traducteur professionnel spécialisé en {genre_affine}'."
        ),
    )
    registre: str = Field(
        min_length=1,
        description="Registre du texte (1 à 2 phrases).",
    )
    style_auctorial: str = Field(
        min_length=1,
        description="Style d'écriture observé (1 à 2 phrases).",
    )
    tonalite_generale: str = Field(
        min_length=1,
        description="Tonalité générale du texte (1 à 2 phrases).",
    )
    pistes_traduction: list[str] = Field(
        min_length=1,
        max_length=PISTES_TRADUCTION_MAX,
        description=(
            "Liste de pistes concrètes pour la traduction. "
            f"Au moins une, au plus {PISTES_TRADUCTION_MAX}. "
            "Fusionner les pistes redondantes."
        ),
    )

    @field_validator("pistes_traduction")
    @classmethod
    def _pistes_non_vides(cls, valeurs: list[str]) -> list[str]:
        return _aucun_element_vide(valeurs)


class CoucheNarrative(BaseModel):
    """État du récit au bloc courant, évolue à chaque bloc."""

    model_config = ConfigDict(extra="forbid")

    resume_narratif: str = Field(
        min_length=1,
        description=(
            "Résumé narratif synthétique au point courant du récit "
            "(max 8 lignes au total)."
        ),
    )
    arcs_en_cours: list[Arc] = Field(
        description=(
            "Arcs narratifs suivis à ce point du récit, chacun annoté "
            "par son `signal_cloture`."
        ),
    )
    tensions: list[str] = Field(
        description="Tensions actuelles du récit.",
    )
    themes_emergents: list[str] = Field(
        description="Thèmes qui émergent dans le récit.",
    )
    references_culturelles_rencontrees: list[str] = Field(
        description="Références culturelles rencontrées dans le texte.",
    )

    @field_validator(
        "tensions",
        "themes_emergents",
        "references_culturelles_rencontrees",
    )
    @classmethod
    def _entrees_non_vides(cls, valeurs: list[str]) -> list[str]:
        return _aucun_element_vide(valeurs)


class AnalyseChapter(ConvertibleModel["AnalyseChapter"]):
    """Fiche d'analyse stratifiée d'un chapitre, snapshot après le bloc courant.

    `ConvertibleModel` avec elle-même pour cible : contrairement aux autres
    phases, la vue `DT` qui circule dans les queues et le cache **est** le
    modèle Pydantic. Il n'y a pas de forme compacte à déplier — la fiche est
    déjà la structure finale, et `PhaseBase` borne son paramètre `M` sur
    `ConvertibleModel`.
    """

    model_config = ConfigDict(extra="forbid")

    chapitre: str = Field(
        min_length=1,
        description="Nom du chapitre analysé.",
    )
    noyau_stable: NoyauStable
    couche_narrative: CoucheNarrative

    @override
    def _build_impl(self) -> "AnalyseChapter":
        return self
