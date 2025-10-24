"""
Types de base et interfaces pour le système de validation.

Ce module définit les protocoles et dataclasses utilisés par tous les checks
de validation et le pipeline de correction.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict

if TYPE_CHECKING:
    from ..llm import LLM
    from ..segment import Chunk


# =============================================================================
# TypedDicts pour error_data (type safety par check)
# =============================================================================


class LineCountErrorData(TypedDict):
    """
    Structure error_data pour LineCountCheck.

    Attributes:
        missing_indices: Indices des lignes manquantes (triés)
        expected_count: Nombre total de lignes attendu
        actual_count: Nombre total de lignes reçu
    """

    missing_indices: list[int]
    expected_count: int
    actual_count: int


class FragmentErrorDetail(TypedDict):
    """
    Détail d'une erreur de fragment pour FragmentCountCheck.

    Attributes:
        line_idx: Index de la ligne problématique
        original_text: Texte original avec séparateurs
        translated_text: Texte traduit avec mauvais nombre de séparateurs
        expected_fragments: Nombre de fragments attendu (basé sur original)
        actual_fragments: Nombre de fragments reçu (basé sur traduction)
    """

    line_idx: int
    original_text: str
    translated_text: str
    expected_fragments: int
    actual_fragments: int


class FragmentCountErrorData(TypedDict):
    """
    Structure error_data pour FragmentCountCheck.

    Attributes:
        errors: Liste des lignes avec mauvais nombre de fragments
    """

    errors: list[FragmentErrorDetail]


# Type union pour tous les error_data possibles
# Garde dict pour extensibilité (nouveaux checks futurs)
ErrorData = LineCountErrorData | FragmentCountErrorData | dict


@dataclass
class CheckResult:
    """
    Résultat d'un check de validation.

    Attributes:
        is_valid: True si la validation a réussi, False sinon
        check_name: Nom unique du check (ex: "line_count", "fragment_count")
        error_message: Message d'erreur descriptif si invalide, None sinon
        error_data: Données détaillées de l'erreur (format dépend du check)
        severity: Niveau de sévérité ("error" bloque, "warning" n'affecte pas)

    Example:
        >>> result = CheckResult(
        ...     is_valid=False,
        ...     check_name="line_count",
        ...     error_message="3 lignes manquantes",
        ...     error_data={"missing_indices": [5, 10, 15]},
        ... )
        >>> print(result)
        ❌ line_count: 3 lignes manquantes
    """

    is_valid: bool
    check_name: str
    error_message: str | None = None
    error_data: ErrorData = field(default_factory=dict)
    severity: Literal["error", "warning"] = "error"

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        if self.is_valid:
            return f"✅ {self.check_name}: OK"
        return f"❌ {self.check_name}: {self.error_message}"


@dataclass
class ValidationContext:
    """
    Contexte partagé entre tous les checks d'un pipeline.

    Ce contexte contient toutes les informations nécessaires pour valider
    et corriger les traductions d'un chunk.

    Attributes:
        chunk: Chunk contenant les textes originaux
        translated_texts: Traductions actuelles {line_index: translated_text}
        original_texts: Textes originaux {line_index: original_text}
        llm: Instance LLM pour corrections (None si lecture seule)
        target_language: Code langue cible (ex: "fr", "en")
        phase: Phase du pipeline ("initial" ou "refined")
        max_retries: Nombre maximum de tentatives de correction par check

    Example:
        >>> context = ValidationContext(
        ...     chunk=chunk,
        ...     translated_texts={0: "Bonjour", 1: "Monde"},
        ...     original_texts={0: "Hello", 1: "World"},
        ...     llm=llm,
        ...     target_language="fr",
        ...     phase="initial",
        ...     max_retries=2,
        ... )
    """

    chunk: "Chunk"
    translated_texts: dict[int, str]
    original_texts: dict[int, str]
    llm: "LLM | None"
    target_language: str
    phase: Literal["initial", "refined"]
    max_retries: int = 2


class Check(Protocol):
    """
    Interface (Protocol) pour tous les checks de validation.

    Un check doit implémenter :
    1. Une propriété `name` retournant un identifiant unique
    2. Une méthode `validate()` qui vérifie la validité
    3. Une méthode `correct()` qui tente de corriger les erreurs

    Example:
        >>> class MyCheck:
        ...     @property
        ...     def name(self) -> str:
        ...         return "my_check"
        ...
        ...     def validate(self, context: ValidationContext) -> CheckResult:
        ...         # Logique de validation
        ...         return CheckResult(is_valid=True, check_name=self.name)
        ...
        ...     def correct(self, context: ValidationContext, error_data: dict) -> dict[int, str]:
        ...         # Logique de correction
        ...         return context.translated_texts
    """

    @property
    def name(self) -> str:
        """
        Nom unique du check.

        Returns:
            Identifiant unique (ex: "line_count", "fragment_count")
        """
        ...

    def validate(self, context: ValidationContext) -> CheckResult:
        """
        Valide les traductions dans le contexte.

        Args:
            context: Contexte de validation contenant chunk et traductions

        Returns:
            CheckResult avec is_valid=True si OK, False avec error_data sinon

        Example:
            >>> result = check.validate(context)
            >>> if not result.is_valid:
            ...     print(f"Erreur: {result.error_message}")
        """
        ...

    def correct(
        self, context: ValidationContext, error_data: ErrorData
    ) -> dict[int, str]:
        """
        Corrige les traductions invalides.

        Cette méthode est appelée automatiquement par le pipeline si validate()
        retourne is_valid=False. Elle doit retourner de nouvelles traductions
        corrigées qui passeront la validation.

        Args:
            context: Contexte de validation (avec traductions actuelles)
            error_data: Données d'erreur retournées par validate()

        Returns:
            Nouvelles traductions corrigées {line_index: corrected_text}

        Raises:
            Exception: Si la correction est impossible (sera loggée par pipeline)

        Example:
            >>> corrected = check.correct(context, result.error_data)
            >>> # Re-valider
            >>> new_result = check.validate(
            ...     dataclasses.replace(context, translated_texts=corrected)
            ... )
            >>> assert new_result.is_valid
        """
        ...
