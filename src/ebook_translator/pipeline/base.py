"""
Classes de base pour le système de phases.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from ebook_translator.checks import Check, ValidationPipeline
from ebook_translator.segmentation.chunk import Chunk
from ebook_translator.segmentation.segmentator import Segmentator
from ebook_translator.stores.store import Store
from ebook_translator.translation.parser import parse_llm_translation_output

if TYPE_CHECKING:
    from ebook_translator.llm.llm_config import LLMConfig
    from ebook_translator.pipeline.context import ChunkContext, PhaseContext, PhaseStats
    from ebook_translator.validation import SaveItem
    from ebook_translator.validator.translation_context import ContexteTraduction


class ExecutionMode(StrEnum):
    """Mode d'exécution d'une phase."""

    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


class PhaseName(StrEnum):
    """Noms standardisés pour les phases."""

    DUMMY = "dummy"
    LITERARY_ANALYSIS = "literary analysis"
    GLOSSARY = "glossary"
    INITIAL = "initial"
    REFINEMENT = "refinement"


class PhaseProtocol(Protocol):
    """Interface structurelle des phases du pipeline.

    Utilisée par Pipeline, PhaseExecutor, StoreManager et ValidationWorkerPool
    pour éviter l'invariance des génériques de PhaseBase. PhaseBase satisfait
    implicitement ce protocole.

    Les overrides de méthodes avec chunk dans les sous-classes de PhaseBase
    doivent déclarer ``chunk: Chunk`` (pas ``ChunkType``) pour garantir la
    conformité LSP.
    """

    name: PhaseName
    execution_mode: ExecutionMode
    max_tokens: int
    overlap_ratio: float
    chunk_type: type[Any]
    depends_on: tuple[Any, ...]
    checks: tuple[Check[Any], ...]

    def store_key(self) -> str: ...
    def put_context(self, context: PhaseContext) -> None: ...
    def validation_pipeline(self) -> ValidationPipeline: ...
    def before_phase(self) -> None: ...
    def after_phase(self, stats: PhaseStats) -> None: ...
    def get_chunks(self) -> Sequence[Chunk]: ...
    def get_store(self) -> Store: ...
    def get_worker_count(self) -> int: ...
    def get_translation_cache(self, chunk: Chunk) -> tuple[dict[int, str], bool]: ...
    def before_chunk(self, chunk: Chunk, context: ChunkContext) -> None: ...
    def render_prompt(self, chunk: Chunk, context: ChunkContext) -> tuple[str, str]: ...
    def get_llm_config(self, chunk: Chunk, context: ChunkContext) -> LLMConfig: ...
    def process_llm_response(
        self, chunk: Chunk, response: str, context: ChunkContext
    ) -> dict[int, str]: ...
    def after_chunk(
        self, chunk: Chunk, result: dict[int, str], context: ChunkContext
    ) -> None: ...
    def save_item_builder(
        self, chunk: Chunk, final_result: dict[int, str]
    ) -> SaveItem: ...


@dataclass
class PhaseBase[ChunkType: Chunk = Chunk](ABC):  # type: ignore
    """
    Classe de base abstraite pour toutes les phases.

    Utilise le pattern Singleton pour garantir une instance unique par classe.
    Configuration déclarative via champs de classe.

    Exemple d'implémentation:
    ```python
        class InitialTranslationPhase(PhaseBase):
            name = "initial"
            max_tokens = 1500
            overlap_ratio = 0.15
            execution_mode = ExecutionMode.PARALLEL
            template_name = TemplateNames.Translate_Base
            checks = [LineCountCheck(), FragmentCountCheck()]


            def render_prompt(cls, chunk: Chunk, context: ChunkContext) -> str:
                return context.llm.renderer.render_translate(context.target_language)
    ```
    """

    # === Configuration obligatoire (à définir dans les sous-classes) ===

    name: PhaseName = field(init=False)
    """Identifiant unique de la phase (ex: 'initial', 'refined', 'quality')"""

    chunk_type: type[ChunkType] = field(init=False)
    """Type de chunk traité par cette phase"""

    max_tokens: int = field(default=0)
    """Nombre maximum de tokens par segment"""

    llm_config: LLMConfig = field(default_factory=lambda: {})

    overlap_ratio: float = field(default=0.0)
    """Ratio de chevauchement entre segments (0.15 = 15%)"""

    execution_mode: ExecutionMode = field(init=False)
    """Mode d'exécution: PARALLEL ou SEQUENTIAL"""

    checks: tuple[Check[Any], ...] = field(init=False)
    """Liste des checks de validation pour cette phase"""

    # === Configuration optionnelle (valeurs par défaut) ===

    depends_on: tuple[type[PhaseBase], ...] = field(
        default_factory=tuple[type["PhaseBase"], ...], init=False
    )
    """Liste des phases dont cette phase dépend"""

    max_workers: int = field(default=4)
    """Nombre de workers (None = auto, utilisé uniquement en mode PARALLEL)"""

    context: PhaseContext = field(init=False)

    # === Validation de configuration ===

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Valide que tous les champs obligatoires sont définis."""
        super().__init_subclass__(**kwargs)

        required_fields = [
            "name",
            "chunk_type",
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
        """
        Retourne la liste des chunks à traiter pour cette phase.

        Doit être surchargé si chunk_type n'est pas Chunk.

        Returns:
            Sequence[Chunk]: Liste des chunks à traiter
        """
        if self.chunk_type != Chunk:
            raise TypeError("get_chunks must be overridden for non-Chunk types")

        return list[Chunk](
            Segmentator(
                epub_source=self.context.html_items,
                max_tokens=self.max_tokens,
                overlap_ratio=self.overlap_ratio,
            ).get_all_segments()
        )

    @classmethod
    def get_translation_cache(cls, chunk: Chunk) -> tuple[dict[int, str], bool]:
        """
        Helper : lit la traduction d'un chunk depuis le store d'une phase.

        - Args:
            - `chunk` : Chunk dont on veut la traduction
        - Returns:
            - `Tuple` contenant :
            1. Dictionnaire `{line_index: texte_traduit ou chaine vide}`
            2. Boolean indiquant si au moins une traduction est manquante
        """
        return cls.get_store().get_from_chunk(chunk)

    def before_phase(self) -> None:  # noqa: B027
        """
        Hook appelé avant le début de la phase.

        Utilisation typique:
        - Initialisation de ressources globales
        - Logging du début de phase
        - Préparation du glossaire
        """
        pass

    def before_chunk(self, chunk: Chunk, context: ChunkContext) -> None:  # noqa: B027
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

    def get_literary_context(
        self, chunk: Chunk, context: ChunkContext
    ) -> ContexteTraduction | None:
        """
        Récupère l'analyse littéraire du chapitre depuis Phase 0 si disponible.

        Délègue à Chapters.get_literary_analysis() qui gère automatiquement :
        - Le mapping Chunk → Chapitre
        - La récupération depuis le store
        - Le filtrage par portée

        Args:
            chunk: Chunk à traduire
            context: Contexte du chunk (non utilisé, requis par signature)

        Returns:
            Analyse littéraire (AnalyseLitteraire) ou None si non disponible
        """
        if not self.context.get_previous_stats(PhaseName.LITERARY_ANALYSIS):
            return None

        # Déléguer à Chapters singleton
        return self.context.chapters.get_literary_analysis(chunk)

    @abstractmethod
    def render_prompt(self, chunk: ChunkType, context: ChunkContext) -> tuple[str, str]:
        """
        Génère le prompt LLM pour ce chunk.

        OBLIGATOIRE: Doit être implémenté par toutes les sous-classes.

        Args:
            chunk: Chunk à traiter
            context: Contexte du chunk (contient llm.renderer, glossary, etc.)

        Returns:
            Prompts (system, user) formaté pour le LLM
        """
        ...

    def get_llm_config(self, chunk: ChunkType, context: ChunkContext) -> LLMConfig:
        """
        Retourne la configuration spécifique du LLM pour cette phase.

        Peut être surchargé pour fournir des paramètres spécifiques
        (ex: température, top_p, etc.)

        Returns:
            Dictionnaire de configuration LLM
        """
        return self.llm_config

    def process_llm_response(
        self, chunk: ChunkType, response: str, context: ChunkContext
    ) -> dict[int, str]:
        """
        Traite la réponse brute du LLM pour ce chunk.

        Par défaut, parse la réponse avec parse_llm_translation_output().
        Peut être surchargé pour un traitement personnalisé.

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
        chunk: ChunkType,
        final_result: dict[int, str],
    ) -> SaveItem:
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

    def after_phase(self, stats: PhaseStats) -> None:  # noqa: B027
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
    def get_store(cls) -> Store:
        """
        Récupère le store associé à cette phase.
        Returns:
            Instance Store pour cette phase
        """
        return cls.context.store_manager.get_store(cls.store_key())

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
            Nombre de workers (défaut: 4) ou 1 si mode SEQUENTIAL
        """
        if self.execution_mode == ExecutionMode.SEQUENTIAL:
            return 1
        return self.max_workers

    @classmethod
    def put_context(cls, context: PhaseContext) -> None:
        """
        Assigne le contexte de la phase à l'instance.

        Args:
            context: Contexte global de la phase
        """
        cls.context = context

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"name='{self.name}', "
            f"mode={self.execution_mode.value}, "
            f"max_tokens={self.max_tokens})"
        )
