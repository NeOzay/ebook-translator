"""
Validation des contextes de traduction (Phase 0).

Valide la structure et le contenu des objets ContexteTraduction.
"""

import json
from functools import cache
from typing import TYPE_CHECKING, Any

from annotationlib import get_annotations

from .translation_context import ContexteTraduction

if TYPE_CHECKING:
    from template.types import AnalyseLitteraire

    from ebook_translator.segmentation.chunk import Chunk


class AnalysisValidator:
    """Valide et vérifie les contextes de traduction."""

    @staticmethod
    @cache
    def load(data: str) -> ContexteTraduction:
        raw_data = json.loads(data)
        validated_data, missing_sections = AnalysisValidator.validate(raw_data)
        if missing_sections:
            raise ValueError(
                f"ContexteTraduction validation failed, missing or invalid sections: {', '.join(missing_sections)}"
            )
        return validated_data

    @staticmethod
    def validate(
        data: dict[str, Any], chunk: Chunk | None = None
    ) -> tuple[ContexteTraduction, list[str]]:
        """
        Valide un contexte JSON contre le schéma ContexteTraduction.

        Args:
            data: Dictionnaire à valider

        Returns:
            1:Le dictionnaire validé (cast en ContexteTraduction)
            2:Liste des sections manquantes ou invalides

        Raises:
            ValueError: Si le contexte est invalide
        """
        missing_sections: list[str] = []
        # Vérifier présence des champs de premier niveau
        if "chapitre" not in data:
            missing_sections.append("chapitre")

        if "scope" not in data:
            if chunk is not None:
                data["scope"] = chunk.scope
            else:
                raise ValueError(
                    "scope is missing and chunk is None, cannot infer scope"
                )

        if "analyse" not in data:
            missing_sections.append("analyse")
        else:
            # Valider structure analyse
            analyse = data["analyse"]
            required_analysis_fields = get_annotations(AnalyseLitteraire).keys()
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

        return data, missing_sections  # type: ignore
