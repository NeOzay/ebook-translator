"""Worker unifié de validation (Bloc B Step 4b).

Pipeline **check-by-check** : les `phase.content_checks` sont parcourus
dans l'ordre de déclaration ; chaque check épuise son budget de retries
sur ses propres failures avant de passer la main au suivant. Aucune
ré-évaluation des checks précédents.

Flux par item :

1. `data ← item.data` (DT déjà schéma-validée par l'executor).
2. Pour chaque `check` dans `phase.content_checks` :

   - `failures = check.run(data, source)`.
   - Tant que `failures` non vide, prendre `failures[0]` (instance
     courante). Tenter jusqu'à `check.max_attempts` retries :

     a. `RETRY_REGISTRY[error_type]` → `entry.build(failure, ctx)` →
        render → LLM → schéma-parse → merge `data ← merge_data(data,
        new.build(), entry.mode)`.
     b. Re-run **uniquement** `check` ; si l'instance n'est plus
        présente (cf. `is_instance_resolved`), passer au failure suivant.

   - Si l'instance survit après `max_attempts`, **drop** les indices
     concernés de `data` (`extract_failure_indices`) et continuer.

3. `phase.save_item_builder(chunk, data)` → `save_queue.put`.

Le chunk peut être sauvegardé partiel (lignes droppées) — c'est le
comportement attendu : on préfère un chunk avec trous à un chunk rejeté.
"""

from __future__ import annotations

import queue
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from itertools import count
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ebook_translator.llm.llm import LLM
from ebook_translator.pipeline.context import CommunContext
from ebook_translator.validation.diagnostics import ErreursType
from template.phase.translation_models import LineIndexed
from template.types import ConvertibleModel

from ..llm.retry_registry import RETRY_REGISTRY, RetryEntry
from ..logger import get_logger
from .failure import from_pydantic_error
from .validation_queue import SaveQueue, ValidationItem, ValidationQueue
from .worker_retry import (
    WorkerRetryContext,
    is_instance_resolved,
    merge_data,
)

if TYPE_CHECKING:
    from ebook_translator.checks.content_check import ChunkSource, ContentCheck
    from ebook_translator.pipeline.base import PhaseProtocol
    from ebook_translator.pipeline.context import ChunkContext
    from ebook_translator.segmentation.chunk import ChunkProtocol

    from .failure import ValidationFailure


@dataclass(frozen=True)
class _RejectOutcome(Exception):
    failures: list[ValidationFailure[Any]]


@dataclass(frozen=True)
class _RejectOutcomeFilter:
    """Sentinelle de sortie anormale avec filtrage des failures déjà renoncées."""

    failures: list[ValidationFailure[Any]]
    indexes_to_remove: set[int]


logger = get_logger(__name__)

counter = count(0)


@dataclass
class ValidationWorker[DT: Any, M: ConvertibleModel[Any] = ConvertibleModel[DT]](ABC):
    validation_queue: ValidationQueue[DT]
    save_queue: SaveQueue[ChunkProtocol, DT]
    phase: PhaseProtocol[ChunkProtocol, DT, M]
    stop_event: threading.Event

    worker_id: int = field(init=False, default_factory=lambda: next(counter))
    validated_count: int = field(init=False, default=0)
    rejected_count: int = field(init=False, default=0)

    @abstractmethod
    def _process(self, item: ValidationItem[DT]) -> DT: ...

    def run(self) -> None:
        """Boucle de consommation. Sortie sur `stop_event.set()`."""

        logger.info(f"[{type(self).__name__}-{self.worker_id}] Démarré")
        while not self.stop_event.is_set():
            try:
                item = self.validation_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                continue

            try:
                data = self._process(item)
                self._save(item, data)
            except _RejectOutcome as rej:
                self._reject(item, rej.failures)
            except Exception as e:
                logger.exception(
                    f"[{type(self).__name__}-{self.worker_id}] Erreur traitement: {e}"
                )
                self.validation_queue.mark_rejected()
                self.rejected_count += 1

        logger.info(
            f"[{type(self).__name__}-{self.worker_id}] Arrêté "
            f"(validated={self.validated_count}, rejected={self.rejected_count})"
        )

    def _save(self, item: ValidationItem[DT], data: DT) -> None:
        save_item = self.phase.save_item_builder(item.chunk, data)
        self.save_queue.put(save_item)
        self.validation_queue.mark_validated()
        self.validated_count += 1
        logger.debug(
            f"[{type(self).__name__}-{self.worker_id}] ✅ Chunk {item.chunk.index} validé"
        )

    def _reject(
        self,
        item: ValidationItem[DT],
        failures: list[ValidationFailure[Any]],
    ) -> None:
        self.validation_queue.mark_rejected()
        self.rejected_count += 1
        summary = "\n".join(f"  • {f.error_type}: {f.msg}" for f in failures)
        logger.error(
            f"[{type(self).__name__}-{self.worker_id}] ❌ Chunk {item.chunk.index} "
            f"rejeté:\n{summary}"
        )


@dataclass
class UnifiedValidationWorker(ValidationWorker[LineIndexed]):
    """Worker thread unique consommant `ValidationQueue[DT]`.

    `DT` est la vue TypedDict transitant en queue. `M` est le modèle
    Pydantic utilisé **uniquement** pour parser la sortie LLM en retry
    (`phase.payload_type.model_validate_json`) — pas porté par
    `ValidationItem` car `M → DT` n'est pas réversible en général.

    Aucune surcharge par phase : le routage retry passe entièrement par
    `RETRY_REGISTRY` (template + build + mode) et par les métadonnées
    `ContentCheck` (`retry_strategy`, `max_attempts`).
    """

    @property
    def target_language(self) -> str:
        """Langue cible, lue depuis `CommunContext` gelé.

        Accès différé (property et non `field(default=...)`) : `CommunContext`
        n'est gelé qu'au démarrage du pipeline, bien après l'import de ce
        module.
        """
        return CommunContext.target_language

    @property
    def llm(self) -> LLM:
        """Client LLM partagé, lu depuis `CommunContext` gelé."""
        return CommunContext.llm

    def _process(self, item: ValidationItem[LineIndexed]) -> LineIndexed:
        """Pipeline check-by-check (cf. docstring module).
        Raise: `_RejectOutcome` si échec non récupérable (schéma KO sur retry).
        """

        chunk = item.chunk
        source = self.phase.chunk_source(chunk)
        data: LineIndexed = LineIndexed(dict(item.data))
        accumulated: list[ValidationFailure[Any]] = list(item.failures)

        for check in self.phase.content_checks:
            outcome = self._correct_one_check(
                check, data, chunk, item.chunk_info, source
            )
            if isinstance(outcome, _RejectOutcome):
                raise _RejectOutcome(outcome.failures + accumulated)
            data, check_failures = outcome
            accumulated.extend(check_failures)

        return data

    def _correct_one_check(
        self,
        check: ContentCheck[LineIndexed, Any],
        data: LineIndexed,
        chunk: ChunkProtocol,
        chunk_info: ChunkContext,
        source: ChunkSource,
    ) -> tuple[LineIndexed, list[ValidationFailure[Any]]] | _RejectOutcome:
        """Boucle de retry sur un seul `check`.

        Retourne `(data_mis_à_jour, failures_consommées)` en cas de
        succès ou de drop ; `_RejectOutcome` si schéma KO sur retry ou
        error_type orphelin du registre.
        """

        consumed: list[ValidationFailure[Any]] = []
        # Indices renoncés par error_type — pour les failures batch
        # (LinesMissing, SentenceInvalid) dont les indices ne disparaissent
        # pas du `data` à la suppression (ils n'y étaient jamais).
        renounced: dict[ErreursType, set[int]] = {}

        def _pending_failures() -> list[ValidationFailure[Any]]:
            """check.run() puis filtre les failures déjà renoncées."""

            raw_failures = check.run(data, source)
            kept: list[ValidationFailure[Any]] = []
            for f in raw_failures:
                indices = f.relevant_indices
                already = renounced.get(f.error_type, set())
                if indices and indices <= already:
                    continue  # tous les indices déjà renoncés → skip
                kept.append(f)
            return kept

        failures = _pending_failures()
        while failures:
            failure = failures[0]
            consumed.append(failure)

            entry = RETRY_REGISTRY.get(failure.error_type)
            if entry is None:
                logger.warning(
                    f"[UnifiedWorker-{self.worker_id}] "
                    f"error_type={failure.error_type!r} sans entrée registre"
                )
                return _RejectOutcome(consumed)

            instance_resolved = False
            for n in range(check.max_attempts):
                retry_outcome = self._run_one_retry(
                    failure=failure,
                    entry=entry,
                    chunk=chunk,
                    chunk_info=chunk_info,
                    source=source,
                    data=data,
                    attempt_index=n,
                    max_attempts=check.max_attempts,
                )
                if isinstance(retry_outcome, _RejectOutcome):
                    return retry_outcome
                data = retry_outcome  # nouveau dict mergé

                # Re-test UNIQUEMENT le check courant (sans filtre
                # renounced : on veut savoir si l'instance LLM-courante
                # a vraiment été corrigée).
                if is_instance_resolved(failure, check.run(data, source), entry.mode):
                    instance_resolved = True
                    break

            if not instance_resolved:
                indices = failure.relevant_indices
                for idx in indices:
                    data.pop(idx, None)
                renounced.setdefault(failure.error_type, set()).update(indices)
                logger.warning(
                    f"[UnifiedWorker-{self.worker_id}] Chunk {chunk.index} "
                    f"drop {len(indices)} ligne(s) sur "
                    f"error_type={failure.error_type!r} "
                    f"(budget {check.max_attempts} épuisé) : {indices}"
                )

            failures = _pending_failures()

        return data, consumed

    def _run_one_retry(
        self,
        failure: ValidationFailure[Any],
        entry: RetryEntry[Any, Any],
        chunk: ChunkProtocol,
        chunk_info: ChunkContext,
        source: ChunkSource,
        data: LineIndexed,
        attempt_index: int,
        max_attempts: int,
    ) -> LineIndexed | _RejectOutcome:
        """Une tentative LLM : render → query → parse schéma → merge.

        Retourne le `data` mergé (succès schéma) ou `_RejectOutcome`
        (schéma KO non récupérable côté worker).
        """

        ctx = WorkerRetryContext(
            target_language=self.target_language,
            chunk=chunk,
            source=source,
            current_data=data,
            max_attempts=max_attempts,
            attempt=attempt_index,
        )
        params = entry.build(failure, ctx)
        sys_prompt, user_prompt = self.llm.renderer.render_prompt(
            entry.template, **params
        )
        log_name = (
            f"{self.phase.name}_chunk_{chunk.index:03d}"
            f"_retry_{failure.error_type}_{attempt_index + 1}"
        )
        # NB: bascule reasoning T2 (PROGRESSIVE_REASONING) déférée Step 4c.

        llm_config = self.llm.client.get_model_preset_config(
            "high", attempt_index == max_attempts - 2
        )
        raw = self.llm.query(
            sys_prompt, user_prompt, log_name=log_name, config=llm_config
        )

        try:
            new_payload = self.phase.payload_type.model_validate_json(raw)
        except ValidationError as e:
            schema_failures = list(from_pydantic_error(e))
            logger.error(
                f"[UnifiedWorker-{self.worker_id}] Chunk {chunk.index} "
                f"retry {failure.error_type} #{attempt_index + 1} : "
                f"schéma KO ({len(schema_failures)} err.)"
            )
            return _RejectOutcome(schema_failures)

        new_data: LineIndexed = new_payload.build()
        return merge_data(data, new_data, entry.mode)
