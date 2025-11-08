"""
Classes de base pour le système de phases.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import ClassVar

from ebook_translator.checks import Check, ValidationPipeline
from ebook_translator.segmentation.segmentator import Chunk
from ebook_translator.pipeline.context import PhaseContext, ChunkContext, PhaseStats
from ebook_translator.config import TemplateNames


class ExecutionMode(Enum):
    """Mode d'exécution d'une phase."""
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


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

            @classmethod
            def render_prompt(cls, chunk: Chunk, context: ChunkContext) -> str:
                return context.llm.renderer.render_translate(context.target_language)
    """

    # === Configuration obligatoire (à définir dans les sous-classes) ===

    name: ClassVar[str]
    """Identifiant unique de la phase (ex: 'initial', 'refined', 'quality')"""

    max_tokens: ClassVar[int]
    """Nombre maximum de tokens par segment"""

    overlap_ratio: ClassVar[float]
    """Ratio de chevauchement entre segments (0.15 = 15%)"""

    execution_mode: ClassVar[ExecutionMode]
    """Mode d'exécution: PARALLEL ou SEQUENTIAL"""

    template_name: ClassVar[TemplateNames]
    """Nom du template Jinja2 à utiliser"""

    # === Configuration optionnelle (valeurs par défaut) ===

    depends_on: ClassVar[list[type["PhaseBase"]]] = []
    """Liste des phases dont cette phase dépend"""

    checks: ClassVar[list[Check]] = []
    """Liste des checks de validation pour cette phase"""

    max_workers: ClassVar[int | None] = None
    """Nombre de workers (None = auto, utilisé uniquement en mode PARALLEL)"""

    store_readonly: ClassVar[bool] = False
    """Si True, le store de cette phase est en lecture seule"""

    # === Singleton ===

    _instances: ClassVar[dict[type["PhaseBase"], "PhaseBase"]] = {}

    def __new__(cls):
        if cls not in cls._instances:
            cls._instances[cls] = super().__new__(cls)
        return cls._instances[cls]

    # === Validation de configuration ===

    def __init_subclass__(cls, **kwargs):
        """Valide que tous les champs obligatoires sont définis."""
        super().__init_subclass__(**kwargs)

        required_fields = ["name", "max_tokens", "overlap_ratio", "execution_mode", "template_name"]
        for field in required_fields:
            if not hasattr(cls, field):
                raise TypeError(f"Phase '{cls.__name__}' must define class attribute '{field}'")

    # === Hooks (méthodes de classe avec implémentation par défaut) ===

    @classmethod
    def before_phase(cls, context: PhaseContext) -> None:
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

    @classmethod
    def before_chunk(cls, chunk: Chunk, context: ChunkContext) -> None:
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

    @classmethod
    @abstractmethod
    def render_prompt(cls, chunk: Chunk, context: ChunkContext) -> str:
        """
        Génère le prompt LLM pour ce chunk.

        OBLIGATOIRE: Doit être implémenté par toutes les sous-classes.

        Args:
            chunk: Chunk à traiter
            context: Contexte du chunk (contient llm.renderer, glossary, etc.)

        Returns:
            Prompt formaté pour le LLM

        Example:
            @classmethod
            def render_prompt(cls, chunk: Chunk, context: ChunkContext) -> str:
                return context.llm.renderer.render_translate(context.target_language)
        """
        pass

    @classmethod
    def after_chunk(
        cls,
        chunk: Chunk,
        result: dict[int, str],
        context: ChunkContext,
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

    @classmethod
    def after_phase(cls, stats: PhaseStats, context: PhaseContext) -> None:
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

    @classmethod
    def store_key(cls) -> str:
        """
        Clé du store pour cette phase.

        Par défaut, utilise le nom de la phase.
        Peut être overridé si nécessaire.

        Returns:
            Clé du store (ex: 'initial', 'refined')
        """
        return cls.name

    @classmethod
    def validation_pipeline(cls) -> ValidationPipeline:
        """
        Pipeline de validation pour cette phase.

        Construit automatiquement depuis cls.checks.

        Returns:
            ValidationPipeline configuré avec les checks de la phase
        """
        return ValidationPipeline(cls.checks)

    @classmethod
    def get_worker_count(cls) -> int:
        """
        Nombre de workers à utiliser (mode PARALLEL uniquement).

        Returns:
            Nombre de workers (défaut: 4 si max_workers est None)
        """
        if cls.max_workers is not None:
            return cls.max_workers
        return 4  # Valeur par défaut

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"name='{self.name}', "
            f"mode={self.execution_mode.value}, "
            f"max_tokens={self.max_tokens})"
        )
