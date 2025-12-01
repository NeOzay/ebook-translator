"""
Classes de base pour le système de phases.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from ebook_translator.checks import Check, ValidationPipeline
from ebook_translator.segmentation.segmentator import Chunk, Segmentator
from ebook_translator.translation.parser import parse_llm_translation_output

if TYPE_CHECKING:
    from ebook_translator.llm.llm_config import LLMConfig
    from ebook_translator.pipeline.context import ChunkContext, PhaseContext, PhaseStats
    from ebook_translator.validation import SaveItem


class ExecutionMode(Enum):
    """Mode d'exécution d'une phase."""

    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


class PhaseName(StrEnum):
    """Noms standardisés pour les phases."""

    DUMMY = "dummy"
    LITERARY_ANALYSIS = "literary analysis"
    INITIAL = "initial"
    REFINEMENT = "refinement"


@dataclass
class PhaseBase(ABC):
    """
    Classe de base abstraite pour toutes les phases.

    Utilise le pattern Singleton pour garantir une instance unique par classe.
    Configuration déclarative via champs de classe.

    Exemple d'implémentation:
        class InitialTranslationPhase(PhaseBase):
            name = "initial"
            max_tokens = 1500
            overlap_ratio = 0.15
            execution_mode = ExecutionMode.PARALLEL
            template_name = TemplateNames.Translate_Base
            checks = [LineCountCheck(), FragmentCountCheck()]


            def render_prompt(cls, chunk: Chunk, context: ChunkContext) -> str:
                return context.llm.renderer.render_translate(context.target_language)
    """

    # === Configuration obligatoire (à définir dans les sous-classes) ===

    name: PhaseName = field(init=False)
    """Identifiant unique de la phase (ex: 'initial', 'refined', 'quality')"""

    max_tokens: int = field(default=0)
    """Nombre maximum de tokens par segment"""

    overlap_ratio: float = field(default=0.0)
    """Ratio de chevauchement entre segments (0.15 = 15%)"""

    execution_mode: ExecutionMode = field(init=False)
    """Mode d'exécution: PARALLEL ou SEQUENTIAL"""

    # template_name: ClassVar[TemplateNames]
    """Nom du template Jinja2 à utiliser"""

    # === Configuration optionnelle (valeurs par défaut) ===

    depends_on: list[type["PhaseBase"]] = field(
        default_factory=list[type["PhaseBase"]], init=False
    )
    """Liste des phases dont cette phase dépend"""

    checks: list[Check[Any]] = field(init=False)
    """Liste des checks de validation pour cette phase"""

    max_workers: int = field(default=4)
    """Nombre de workers (None = auto, utilisé uniquement en mode PARALLEL)"""

    store_readonly: bool = False
    """Si True, le store de cette phase est en lecture seule"""

    context: "PhaseContext" = field(init=False)

    # === Singleton ===

    _instances: ClassVar[dict["PhaseBase", "PhaseBase"]] = {}

    # === Validation de configuration ===

    def __init_subclass__(cls, **kwargs: Any):
        """Valide que tous les champs obligatoires sont définis."""
        super().__init_subclass__(**kwargs)

        required_fields = [
            "name",
            "max_tokens",
            "overlap_ratio",
            "execution_mode",
            "checks",
        ]
        for _field in required_fields:
            if not hasattr(cls, _field):
                raise TypeError(
                    f"Phase '{cls.__name__}' must define class attribute '{_field}'"
                )

    # === Hooks (méthodes de classe avec implémentation par défaut) ===

    def get_chunks(self) -> Sequence[Chunk]:
        return list(
            Segmentator(
                self.context.html_items,
                max_tokens=self.max_tokens,
                overlap_ratio=self.overlap_ratio,
            ).get_all_segments()
        )

    def get_translation_cache(self, chunk: "Chunk") -> tuple[dict[int, str], bool]:
        """
        Helper: lit la traduction d'un chunk depuis le store d'une phase.

        Args:
            - phase_name: Nom de la phase
            - chunk: Chunk dont on veut la traduction

        Returns:
            Tuple contenant:
            - Dictionnaire {line_index: texte_traduit ou chaine vide}
            - Boolean indiquant si au moins une traduction est manquante
        """
        return self.context.store_manager.get_translate(self.store_key(), chunk)

    def before_phase(self) -> None:  # noqa: B027
        """
        Hook appelé avant le début de la phase.

        Utilisation typique:
        - Initialisation de ressources globales
        - Logging du début de phase
        - Préparation du glossaire

        Args:
            context: Contexte global de la phase
        """
        pass

    def before_chunk(self, chunk: Chunk, context: "ChunkContext") -> None:  # noqa: B027
        """
        Hook appelé avant le traitement d'un chunk.

        Utilisation typique:
        - Export du glossaire
        - Logging de progression
        - Préparation de données spécifiques au chunk

        Args:
            chunk: Chunk à traiter
            context: Contexte du chunk
        """
        pass

    @abstractmethod
    def render_prompt(self, chunk: Chunk, context: "ChunkContext") -> str:
        """
        Génère le prompt LLM pour ce chunk.

        OBLIGATOIRE: Doit être implémenté par toutes les sous-classes.

        Args:
            chunk: Chunk à traiter
            context: Contexte du chunk (contient llm.renderer, glossary, etc.)

        Returns:
            Prompt formaté pour le LLM

        Example:

            def render_prompt(cls, chunk: Chunk, context: ChunkContext) -> str:
                return context.llm.renderer.render_translate(context.target_language)
        """
        ...

    def source_content(self, chunk: Chunk, context: "ChunkContext") -> str:
        """
        Retourne le contenu source du chunk sous forme de chaîne de caractères.

        Args:
            chunk: Chunk à traiter

        Returns:
            Contenu source du chunk en tant que string
        """
        return str(chunk)

    def llm_config(self, chunk: Chunk, context: "ChunkContext") -> "LLMConfig":
        """
        Retourne la configuration spécifique du LLM pour cette phase.

        Peut être surchargé pour fournir des paramètres spécifiques
        (ex: température, top_p, etc.)

        Returns:
            Dictionnaire de configuration LLM
        """
        return {}

    def process_llm_response(
        self, chunk: Chunk, response: str, context: "ChunkContext"
    ) -> dict[int, str]:
        """
        Traite la réponse brute du LLM pour ce chunk.

        Par défaut, parse la réponse avec parse_llm_translation_output().
        Peut être surchargé pour parser la réponse et extraire les traductions.

        Args:
            chunk: Chunk traité
            response: Réponse brute du LLM
            context: Contexte du chunk
        Returns:
            Dictionnaire des traductions (mapping line_index -> translated_text)
        """
        return parse_llm_translation_output(response)

    def save_item_builder(
        self,
        chunk: "Chunk",
        final_result: dict[int, str],
    ) -> "SaveItem":
        """
        Construit un SaveItem à partir du chunk et des résultats finaux.

        Args:
            chunk: Chunk traité
            final_result: Dictionnaire des traductions (mapping line_index -> translated_text)

        Returns:
            Instance SaveItem prête à être envoyée au SaveQueue
        """
        from ebook_translator.validation.validation_worker import (
            default_save_item_builder,
        )

        return default_save_item_builder(chunk, final_result)

    def after_chunk(  # noqa: B027
        self,
        chunk: Chunk,
        result: dict[int, str],
        context: "ChunkContext",
    ) -> None:
        """
        Hook appelé après le traitement d'un chunk.

        Utilisation typique:
        - Apprentissage du glossaire
        - Logging de résultats
        - Statistiques intermédiaires

        Args:
            chunk: Chunk traité
            result: Traductions générées (mapping line_index -> translated_text)
            context: Contexte du chunk
        """
        pass

    def after_phase(self, stats: "PhaseStats") -> None:  # noqa: B027
        """
        Hook appelé après la fin de la phase.

        Utilisation typique:
        - Rapport de statistiques
        - Nettoyage de ressources
        - Export de résultats

        Args:
            stats: Statistiques d'exécution de la phase
            context: Contexte global de la phase
        """
        pass

    # === Propriétés calculées ===

    def store_key(self) -> str:
        """
        Clé du store pour cette phase.

        Par défaut, utilise le nom de la phase.
        Peut être overridé si nécessaire.

        Returns:
            Clé du store (ex: 'initial', 'refined')
        """
        return self.name

    def validation_pipeline(self) -> ValidationPipeline:
        """
        Pipeline de validation pour cette phase.

        Construit automatiquement depuis cls.checks.

        Returns:
            ValidationPipeline configuré avec les checks de la phase
        """
        return ValidationPipeline(self.checks)

    def get_worker_count(self) -> int:
        """
        Nombre de workers à utiliser (mode PARALLEL uniquement).

        Returns:
            Nombre de workers (défaut: 4 si max_workers est None)
        """
        if self.execution_mode == ExecutionMode.SEQUENTIAL:
            return 1
        return self.max_workers

    def put_context(self, context: "PhaseContext") -> None:
        """
        Assigne le contexte de la phase à l'instance.

        Args:
            context: Contexte global de la phase
        """
        self.context = context

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"name='{self.name}', "
            f"mode={self.execution_mode.value}, "
            f"max_tokens={self.max_tokens})"
        )
