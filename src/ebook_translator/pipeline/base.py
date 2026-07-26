"""
Classes de base pour le système de phases.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Protocol, cast, override
from warnings import deprecated

from pydantic import BaseModel, ValidationError

from ebook_translator.checks import Check, ValidationPipeline
from ebook_translator.checks.content_check import ChunkSource, ContentCheck
from ebook_translator.llm.clients.client import ClientProviderProtocol
from ebook_translator.llm.llm_config import JsonRequestConfig, LLMConfig
from ebook_translator.persistence.chunk_persister import ChunkPersister
from ebook_translator.pipeline.phase_storage import PhaseStorage
from ebook_translator.segmentation.chunk import Chunk, ChunkProtocol
from ebook_translator.segmentation.segmentator import Segmentator
from ebook_translator.stores.byte_store import ByteStore, FileByteStore
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


def validate_data[DT](
    content_checks: Sequence[ContentCheck[DT, Any]],
    data: DT,
    source: ChunkSource,
) -> list[ValidationFailure[Any]]:
    """Lance les `content_checks` sur un `data` (TypedDict) déjà bien formé."""

    failures: list[ValidationFailure[Any]] = []
    for check in content_checks:
        failures.extend(check.run(data, source))
    return failures


def validate_payload[M: ConvertibleModel[Any]](
    payload_type: type[M],
    content_checks: Sequence[ContentCheck[Any, Any]],
    raw: str | M,
    source: ChunkSource,
) -> M | list[ValidationFailure[Any]]:
    """Pipeline schéma puis contenu (post-LLM).

    Court-circuite sur erreur schéma : les `content_checks` ne tournent
    jamais sur un payload structurellement KO.
    """

    if isinstance(raw, ConvertibleModel):
        payload: M = cast(M, raw)
    else:
        try:
            payload = payload_type.model_validate(raw)
        except ValidationError as e:
            return list(from_pydantic_error(e))

    failures = validate_data(content_checks, payload.build(), source)
    if failures:
        return failures
    return payload


@dataclass(frozen=True)
class _ChunkSourceAdapter:
    """Implémentation `ChunkSource` minimale autour d'un mapping idx → texte."""

    indices: tuple[int, ...]
    texts: dict[int, str]

    @property
    def line_indices(self) -> tuple[int, ...]:
        return self.indices

    def text_at(self, index: int) -> str:
        return self.texts[index]


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


class PhaseProtocol[ChunkType: ChunkProtocol = Any, DT: Any = Any, M: Any = Any](
    Protocol
):
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
    payload_type: type[M]
    data_type: type[DT]
    content_checks: tuple[ContentCheck[DT, Any], ...]

    @classmethod
    def store_key(cls) -> str: ...
    def chunk_source(self, chunk: ChunkType) -> ChunkSource: ...
    def validate_data(
        self, data: DT, source: ChunkSource
    ) -> list[ValidationFailure[Any]]: ...
    def validate_payload(
        self, raw: str | M, source: ChunkSource
    ) -> M | list[ValidationFailure[Any]]: ...
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
    def get_translation_cache(self, chunk: ChunkType) -> tuple[DT, set[int]] | None: ...
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
    @deprecated(
        "Use is_chunk_cached + load_chunk_view instead for new phases with ChunkPersister"
    )
    def process_llm_response(
        self, chunk: ChunkType, response: str, context: ChunkContext
    ) -> dict[int, str]: ...
    def after_chunk(
        self, chunk: ChunkType, data: DT, context: ChunkContext
    ) -> None: ...
    def save_item_builder(self, chunk: ChunkType, data: DT) -> SaveItem[ChunkType]: ...


@dataclass
class PhaseBase[
    ChunkType: ChunkProtocol = Chunk,
    DT: Any = Any,
    M: ConvertibleModel[  # Ne pas redéfinir dans les sous-classes, Type du payload LLM déduit avec DT
        Any
    ] = ConvertibleModel[
        DT
    ],
](ABC, PhaseProtocol[ChunkType, DT, M]):
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

    payload_type: type[M] = field(init=False)
    """Modèle Pydantic du payload LLM. Sous-classes migrées (étape 6+) le
    surchargent (`LineIndexedLLMResponse`, `AnalyseChapter`, `LLMGlossaryModel`).

    `ClassVar` plutôt que dataclass field : doit être une donnée de classe
    pas d'instance (sinon le `default_factory` écrase la valeur posée par
    la sous-classe à l'instanciation).
    """

    data_type: type[DT] = field(init=False)

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

    content_checks: tuple[ContentCheck[DT, Any], ...] = field(default=(), init=False)
    """Checks contenu post-parsing (nouveau Protocol). Chaque check porte
    son propre `retry_strategy` et `max_attempts` ; il n'y a pas d'override
    au niveau phase. Pour le chemin schéma KO (Pydantic), voir
    `llm.retry_registry.SCHEMA_RETRY_STRATEGY` / `SCHEMA_MAX_ATTEMPTS`."""

    persister: ChunkPersister[ChunkType, DT] | None = field(default=None, init=False)
    """Stratégie de cache (`LineIndexedPersister`, `MemoizedChunkPersister`).

    `None` sur la base = phase pas encore migrée vers la nouvelle voie ;
    les méthodes `is_chunk_cached` / `load_chunk_view` / `persist_chunk`
    lèvent alors `NotImplementedError`. Les sous-classes migrées (étape
    7a-bis.7) la définissent explicitement.

    Cohabite avec `get_translation_cache` legacy le temps de la migration.
    Sera retiré l'étape 9 avec le legacy `Store`.
    """

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

    @override
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
    def get_translation_cache(self, chunk: ChunkType) -> tuple[DT, set[int]] | None:
        """Délègue à `PhaseStorage.load` puis re-valide via `content_checks`.

        Toute failure invalide la cache entière (`None`) — le chunk est
        re-traduit. Stratégie all-or-nothing : un cache partiellement
        valide n'est pas exploité (à raffiner si gaspillage observé).
        """

        if self.persister is None:
            return None
        data, missing = self.storage.load(chunk)
        if data is None:
            return None
        if self.content_checks and self.validate_data(data, self.chunk_source(chunk)):
            return None
        return data, missing

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

    def validate_data(
        self, data: DT, source: ChunkSource
    ) -> list[ValidationFailure[Any]]:
        """Chemin **cache** : `content_checks` sur TypedDict déjà bien formé."""

        return validate_data(self.content_checks, data, source)

    def validate_payload(
        self, raw: str | M, source: ChunkSource
    ) -> M | list[ValidationFailure[Any]]:
        """Chemin **post-LLM** : schéma puis contenu."""

        return validate_payload(self.payload_type, self.content_checks, raw, source)

    def chunk_source(self, chunk: ChunkType) -> ChunkSource:
        """Adapte un chunk en `ChunkSource` consommable par `ContentCheck`.

        Indices chunk-local (`0..N`) issus de l'ordre de `fetch_body()`,
        textes source associés. Override pour les phases dont le `Chunk`
        n'expose pas `fetch_body` (ex. Phase 0 / glossaire).
        """

        body = list(chunk.fetch_body())
        return _ChunkSourceAdapter(
            indices=tuple(range(len(body))),
            texts={i: text for i, (_, _, text) in enumerate(body)},
        )

    # === Persistance via ChunkPersister (étape 7a-bis) ===

    BYTE_STORE_SUBDIR: ClassVar[str] = "_v2"
    """Sous-dossier dédié au `FileByteStore` v2 — évite la collision de
    noms avec le `Store` legacy. Fusionné racine à l'étape 9.
    """

    def get_byte_store(self) -> ByteStore:
        """`ByteStore` principal de la phase. Override possible."""

        return FileByteStore(self.get_store().cache_dir / self.BYTE_STORE_SUBDIR)

    def get_byte_fallback_store(self) -> ByteStore | None:
        """`ByteStore` amont (chaîne inter-phases). Override possible (Phase 2 → Phase 1)."""

        return None

    @cached_property
    def storage(self) -> PhaseStorage[ChunkType, DT]:
        """Composeur `persister` + `ByteStore`(s). Cache l'instance.

        Lève `NotImplementedError` si `persister` n'est pas défini sur la
        sous-classe (phase non migrée vers la nouvelle voie).
        """

        if self.persister is None:
            raise NotImplementedError(f"Phase {self.name!r} sans persister configuré.")
        return PhaseStorage(
            self.persister, self.get_byte_store(), self.get_byte_fallback_store()
        )

    def is_chunk_cached(self, chunk: ChunkType) -> bool:
        return self.storage.is_cached(chunk)

    def load_chunk_view(self, chunk: ChunkType) -> tuple[DT | None, set[int]]:
        return self.storage.load(chunk)

    def persist_chunk(self, chunk: ChunkType, data: DT) -> None:
        self.storage.persist(chunk, data)

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

    def save_item_builder(self, chunk: ChunkType, data: DT) -> SaveItem[ChunkType]:
        return self.storage.save_item(chunk, data)

    def after_chunk(  # noqa: B027
        self,
        chunk: ChunkType,
        data: DT,
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
