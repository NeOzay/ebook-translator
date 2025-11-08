"""
Validation des analyses littéraires (Phase 0).

Valide la structure et le contenu des objets ChapterAnalysis.
"""

from typing import Any
from .schema import ChapterAnalysis


class AnalysisValidator:
    """Valide et vérifie les analyses littéraires."""

    REQUIRED_FIELDS = [
        "chapter_name",
        "analysis_version",
        "blocks_analyzed",
        "total_blocks",
        "status",
        "characters",
        "locations",
        "plot_elements",
        "themes",
        "narrative_techniques",
        "terminology",
        "stylistic_notes",
        "translation_considerations",
    ]

    @staticmethod
    def validate(data: dict[str, Any]) -> ChapterAnalysis:
        """
        Valide une analyse JSON contre le schéma ChapterAnalysis.

        Args:
            data: Dictionnaire à valider

        Returns:
            Le dictionnaire validé (cast en ChapterAnalysis)

        Raises:
            ValueError: Si la validation échoue
        """
        # Vérifier présence des champs requis
        for field in AnalysisValidator.REQUIRED_FIELDS:
            if field not in data:
                raise ValueError(f"Missing required field: {field}")

        # Valider status
        if data["status"] not in ["in_progress", "complete"]:
            raise ValueError(f"Invalid status: {data['status']}")

        # Valider blocks_analyzed
        if not isinstance(data["blocks_analyzed"], int):
            raise ValueError("blocks_analyzed must be int")

        if not isinstance(data["total_blocks"], int):
            raise ValueError("total_blocks must be int")

        # Valider cohérence blocks
        if data["blocks_analyzed"] > data["total_blocks"]:
            raise ValueError(
                f"blocks_analyzed ({data['blocks_analyzed']}) > total_blocks ({data['total_blocks']})"
            )

        # Valider status cohérence
        if data["status"] == "complete" and data["blocks_analyzed"] != data["total_blocks"]:
            raise ValueError(
                f"Status 'complete' but blocks_analyzed ({data['blocks_analyzed']}) != total_blocks ({data['total_blocks']})"
            )

        # Valider structure characters
        if "characters" in data:
            if "present" not in data["characters"]:
                raise ValueError("characters.present is required")
            if "mentioned" not in data["characters"]:
                raise ValueError("characters.mentioned is required")

        # Valider structure locations
        if "locations" in data:
            if "primary" not in data["locations"]:
                raise ValueError("locations.primary is required")
            if "secondary" not in data["locations"]:
                raise ValueError("locations.secondary is required")

        # Valider structure terminology
        if "terminology" in data:
            if "specialized_terms" not in data["terminology"]:
                raise ValueError("terminology.specialized_terms is required")
            if "proper_nouns" not in data["terminology"]:
                raise ValueError("terminology.proper_nouns is required")

        return data  # type: ignore

    @staticmethod
    def is_complete(analysis: ChapterAnalysis) -> bool:
        """
        Vérifie si une analyse est complète.

        Args:
            analysis: Analyse à vérifier

        Returns:
            True si l'analyse est complète
        """
        return (
            analysis["status"] == "complete"
            and analysis["blocks_analyzed"] == analysis["total_blocks"]
        )

    @staticmethod
    def get_completion_ratio(analysis: ChapterAnalysis) -> float:
        """
        Calcule le ratio de complétion d'une analyse.

        Args:
            analysis: Analyse à évaluer

        Returns:
            Ratio entre 0.0 et 1.0
        """
        if analysis["total_blocks"] == 0:
            return 0.0
        return analysis["blocks_analyzed"] / analysis["total_blocks"]
