"""
Classes de base pour le système de phases.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Protocol, cast, override

from pydantic import BaseModel, ValidationError

from ebook_translator.checks import Check, ValidationPipeline
from ebook_translator.checks.content_check import ChunkSource, ContentCheck
from ebook_translator.llm.clients.client import ClientProviderProtocol
from ebook_translator.llm.llm_config import JsonRequestConfig, LLMConfig
from ebook_translator.segmentation.chunk import Chunk, ChunkProtocol
from ebook_translator.segmentation.segmentator import Segmentator
from ebook_translator.stores.store import Store
from ebook_translator.translation.parser import parse_llm_translation_output
from ebook_translator.validation.failure import ValidationFailure, from_pydantic_error
from template.types import ConvertibleModel

if TYPE_CHECKING:
    from ebook_translator.pipeline.context import (
        ChunkContext,
        PhaseContext,
        PhaseStats,
    )
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


class PhaseProtocol[ChunkType: ChunkProtocol = Any](Protocol):
    """Interface structurelle des phases du pipeline.

    Utilisée par Pipeline, PhaseExecutor, StoreManager et ValidationWorkerPool
    pour éviter l'invariance des génériques de PhaseBase. PhaseBase satisfait
    implicitement ce protocole.

    Les overrides de méthodes avec chunk dans les sous-classes de PhaseBase
    doivent déclarer ``chunk: Chunk`` (pas ``ChunkType``) pour garantir la
    conformité LSP.
    """

    name: PhaseName
    output_type: Literal["Text"] | type[BaseModel]
    execution_mode: ExecutionMode
    max_tokens: int
    overlap_ratio: float
    chunk_type: type[ChunkType]

    @classmethod
    def store_key(cls) -> str: ...
    def put_context(self, context: PhaseContext) -> None: ...
    @classmethod
    def validation_pipeline(cls) -> ValidationPipeline: ...
    def before_phase(self) -> None: ...
    def after_phase(self, stats: PhaseStats) -> None: ...
    def get_chunks(self) -> Sequence[ChunkType]: ...
    def get_store(self) -> Store: ...
    def get_worker_count(self) -> int: ...
    @classmethod
    def get_checks(cls) -> tuple[Check[Any], ...]: ...
    @classmethod
    def get_dependencies(cls) -> tuple[type[PhaseProtocol], ...]: ...
    def get_translation_cache(
        self, chunk: ChunkType
    ) -> tuple[dict[int, str], bool]: ...
    def before_chunk(self, chunk: ChunkType, context: ChunkContext) -> None: ...
    def render_prompt(
        self, chunk: ChunkType, context: ChunkContext
    ) -> tuple[str, str]: ...
    def get_llm_config(
        self, chunk: ChunkType, context: ChunkContext
    ) -> (
        LLMConfig
        | ClientProviderProtocol
        | JsonRequestConfig[ConvertibleModel[Any]]
        | None
    ): ...
    def process_llm_response(
        self, chunk: ChunkType, response: str, context: ChunkContext
    ) -> dict[int, str]: ...
    def after_chunk(
        self, chunk: ChunkType, result: dict[int, str], context: ChunkContext
    ) -> None: ...
    def save_item_builder(
        self, chunk: ChunkType, final_result: dict[int, str]
    ) -> SaveItem: ...


def validate_payload[M: ConvertibleModel[Any]](
    payload_type: type[M],
    content_checks: tuple[ContentCheck[M, Any], ...],
    raw: str | M,
    source: ChunkSource,
) -> M | list[ValidationFailure[Any]]:
    """Pipeline de validation unifié : schéma puis contenu.

    Étapes :
        1. Si `raw` est déjà une instance de `ConvertibleModel`, considère
           le schéma comme validé (cas Phase 0 / glossaire via Instructor).
        2. Sinon, `payload_type.model_validate(raw)`. Toute `ValidationError`
           remonte sous forme de `ValidationFailure` typés via
           `from_pydantic_error` et la fonction sort immédiatement (le
           contenu n'est pas vérifié sur un schéma KO).
        3. Si schéma OK, exécute chaque `ContentCheck` ; collecte toutes les
           failures non-nulles. Si au moins une, retourne la liste ; sinon
           retourne le payload typé.

    Returns:
        - `M` validé schéma + contenu, ou
        - `list[ValidationFailure]` (1+ erreurs schéma OU 1+ erreurs contenu,
          jamais un mix : la fonction court-circuite après échec schéma).
    """

    if isinstance(raw, ConvertibleModel):
        payload: M = cast(M, raw)
    else:
        try:
            payload = payload_type.model_validate(raw)
        except ValidationError as e:
            return list(from_pydantic_error(e))

    content_failures: list[ValidationFailure[Any]] = []
    for check in content_checks:
        content_failures.extend(check.run(payload, source))
    if content_failures:
        return content_failures
    return payload


@dataclass
class PhaseBase[
    ChunkType: ChunkProtocol = Chunk,
    M: ConvertibleModel[Any] = ConvertibleModel[Any],
](
    ABC, PhaseProtocol[ChunkType]
):  # type: ignore
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

    output_type: Literal["Text"] | type[BaseModel] = field(init=False, default="Text")

    chunk_type: type[ChunkType] = field(init=False)
    """Type de chunk traité par cette phase"""

    max_tokens: int = field()
    """Nombre maximum de tokens par segment"""

    llm: ClientProviderProtocol | LLMConfig | None = field(default=None)

    overlap_ratio: float = field(default=0.0)
    """Ratio de chevauchement entre segments (0.15 = 15%)"""

    head_tail_balance: float = field(default=0.75)
    """Facteur de balance pour le chevauchement head/tail (0.75 = 75% head, 25% tail)"""

    execution_mode: ExecutionMode = field(init=False)
    """Mode d'exécution: PARALLEL ou SEQUENTIAL"""

    checks: tuple[Check[Any], ...] = field(
        init=False, default_factory=tuple[Check[Any], ...]
    )
    """Liste des checks de validation pour cette phase (legacy, étape 9 dépose)"""

    # === Configuration nouvelle API (étape 5+) ===

    payload_type: ClassVar[type[ConvertibleModel[Any]]] = cast(
        "type[ConvertibleModel[Any]]", ConvertibleModel
    )
    """Modèle Pydantic du payload LLM. Sous-classes migrées (étape 6+) le
    surchargent (`LineIndexedTranslation`, `AnalyseChapter`, `LLMGlossaryModel`).

    `ClassVar` plutôt que dataclass field : doit être une donnée de classe
    pas d'instance (sinon le `default_factory` écrase la valeur posée par
    la sous-classe à l'instanciation).
    """

    content_checks: ClassVar[tuple[ContentCheck[Any, Any], ...]] = ()
    """Checks contenu post-parsing (nouveau Protocol). Chaque check porte
    son propre `retry_strategy` et `max_attempts` ; il n'y a pas d'override
    au niveau phase. Pour le chemin schéma KO (Pydantic), voir
    `llm.retry_registry.SCHEMA_RETRY_STRATEGY` / `SCHEMA_MAX_ATTEMPTS`."""

    # === Configuration optionnelle (valeurs par défaut) ===

    depends_on: tuple[type[PhaseProtocol], ...] = field(
        default_factory=tuple[type[PhaseProtocol], ...], init=False
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

    def get_chunks(self) -> Sequence[ChunkType]:
        """
        Retourne la liste des chunks à traiter pour cette phase.

        Doit être surchargé si chunk_type n'est pas Chunk.

        Returns:
            Sequence[Chunk]: Liste des chunks à traiter
        """
        if self.chunk_type == Chunk:
            return cast(
                list[ChunkType],
                Segmentator(
                    epub_source=self.context.html_pages,
                    max_tokens=self.max_tokens,
                    overlap_ratio=self.overlap_ratio,
                    head_tail_balance=self.head_tail_balance,
                ).get_all_segments(),
            )

        raise TypeError("get_chunks must be overridden for non-Chunk types")

    @override
    def get_translation_cache(self, chunk: ChunkType) -> tuple[dict[int, str], bool]:
        """
        Helper : lit la traduction d'un chunk depuis le store d'une phase.

        - Args:
            - `chunk` : Chunk dont on veut la traduction
        - Returns:
            - `Tuple` contenant :
            1. Dictionnaire `{line_index: texte_traduit ou chaine vide}`
            2. Boolean indiquant si au moins une traduction est manquante
        """
        return self.get_store().get_from_chunk(chunk, use_fallback=False)

    def before_phase(self) -> None:  # noqa: B027
        """
        Hook appelé avant le début de la phase.

        Utilisation typique:
        - Initialisation de ressources globales
        - Logging du début de phase
        - Préparation du glossaire
        """
        pass

    def before_chunk(
        self, chunk: ChunkType, context: ChunkContext
    ) -> None:  # noqa: B027
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

    def get_llm_config(
        self, chunk: ChunkType, context: ChunkContext
    ) -> (
        LLMConfig
        | ClientProviderProtocol
        | JsonRequestConfig[ConvertibleModel[Any]]
        | None
    ):
        """
        Retourne la configuration spécifique du LLM pour cette phase.

        Peut être surchargé pour fournir des paramètres spécifiques
        (ex: température, top_p, etc.)

        Returns:
            Dictionnaire de configuration LLM
        """
        return self.llm

    def validate(
        self, raw: str | M, source: ChunkSource
    ) -> M | list[ValidationFailure[Any]]:
        """Pipeline de validation unifié pour cette phase.

        Délègue à la fonction libre `validate_payload`. Voir sa docstring
        pour la sémantique (court-circuit schéma KO, séparation
        schéma/contenu, sortie typée).

        Aucune phase existante ne l'appelle en étape 5 ; les phases sont
        migrées une par une à partir de l'étape 6.
        """

        # `payload_type` est une `ClassVar[type[ConvertibleModel[Any]]]` au
        # niveau de PhaseBase ; les sous-classes la rétrécissent à leur `M`
        # concret. Le cast ré-aligne le type de retour avec le `M` du
        # paramètre générique de la classe pour les consommateurs.
        result = validate_payload(self.payload_type, self.content_checks, raw, source)
        return cast("M | list[ValidationFailure[Any]]", result)

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
        chunk: ChunkType,
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

    def get_store(self) -> Store:
        """
        Récupère le store associé à cette phase.
        Returns:
            Instance Store pour cette phase
        """
        return self.context.store_manager.get_store(self.store_key())

    @classmethod
    def validation_pipeline(cls) -> ValidationPipeline:
        """
        Pipeline de validation pour cette phase.

        Construit automatiquement depuis cls.checks.

        Returns:
            ValidationPipeline configuré avec les checks de la phase
        """
        return ValidationPipeline(cls.checks)

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
    def get_checks(cls) -> tuple[Check[Any], ...]:
        return cls.checks

    @classmethod
    @override
    def get_dependencies(cls) -> tuple[type[PhaseProtocol], ...]:
        return cls.depends_on

    def put_context(self, context: PhaseContext) -> None:
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
