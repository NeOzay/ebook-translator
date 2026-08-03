"""Tests `UnifiedValidationWorker` (Bloc B Step 4b).

Scénarios couverts (LLM mocké, phase et payload Pydantic minimaux) :

- T1 succès direct (validate_data → [] dès le premier passage).
- T1 échec content_check → T2 réussit après merge.
- T1 échec → T2 échec → reject (max_attempts dépassé).
- error_type sans entrée registre → reject immédiat.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import Mock

import pytest
from pydantic import model_validator

from ebook_translator.checks.content_check import ChunkSource
from ebook_translator.pipeline.context import CommunContext
from ebook_translator.validation.diagnostics import ErreursType
from ebook_translator.validation.failure import ValidationFailure
from ebook_translator.validation.retry_strategy import RetryStrategy
from ebook_translator.validation.unified_worker import UnifiedValidationWorker
from ebook_translator.validation.validation_queue import (
    SaveQueue,
    ValidationItem,
    ValidationQueue,
)
from template.types import ConvertibleModel

# ---------- Fakes : payload, source, chunk, phase, llm ----------


class _FakePayload(ConvertibleModel[dict[int, str]]):
    """Pydantic minimal — porte un `dict[int, str]` arbitraire.

    Comme `LineIndexedLLMResponse`, il parse la **chaîne brute** du LLM dans
    un validateur `mode="before"` : le worker appelle `model_validate` sur le
    texte, pas `model_validate_json`. Un fake qui n'accepterait que du JSON
    validerait un chemin que la production n'emprunte jamais.
    """

    data: dict[int, str]

    @model_validator(mode="before")
    @classmethod
    def _parse_raw(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        parsed: dict[int, str] = {}
        for line in value.splitlines():
            if m := re.match(r"^<(\d+)/>(.*)$", line, re.DOTALL):
                parsed[int(m.group(1))] = m.group(2)
        return {"data": parsed}

    def _build_impl(self) -> dict[int, str]:
        return dict(self.data)


@dataclass(frozen=True)
class _FakeSource:
    texts: dict[int, str]

    @property
    def line_indices(self) -> Iterable[int]:
        return self.texts.keys()

    def text_at(self, index: int) -> str:
        return self.texts[index]


@dataclass(frozen=True)
class _FakeChunk:
    index: int = 0

    def fetch_body(self) -> Iterable[tuple[Any, Any, str]]:
        return iter(())

    def prepare_for_prompt(
        self, index_to_mark: list[int] | None = None, **_: object
    ) -> str:
        return f"<chunk {self.index} indices={index_to_mark}>"


@dataclass
class _FakeCheck:
    """ContentCheck fake : émet une failure si une ligne attendue manque."""

    error_type: ErreursType = ErreursType.LINES_MISSING
    retry_strategy: RetryStrategy = RetryStrategy.NORMAL_ONLY
    max_attempts: int = 2
    expected_indices: tuple[int, ...] = (0, 1)

    def run(
        self, data: dict[int, str], source: ChunkSource
    ) -> list[ValidationFailure[Any]]:
        missing = [i for i in self.expected_indices if i not in data]
        if not missing:
            return []
        return [
            ValidationFailure[Any](
                error_type=self.error_type,
                msg=f"{len(missing)} manquantes",
                ctx={"missing_indices": missing},
                relevant_indices=frozenset(missing),
            )
        ]


class _FakeRenderer:
    def render_prompt(self, template: Any, **kwargs: Any) -> tuple[str, str]:
        return ("sys", f"user:{kwargs}")


class _FakeClient:
    """Surface minimale attendue par le worker sur `llm.client`."""

    def get_model_preset_config(self, preset: str, reasoning: bool) -> None:
        return None


@dataclass
class _FakeLLM:
    renderer: _FakeRenderer = field(default_factory=_FakeRenderer)
    client: _FakeClient = field(default_factory=_FakeClient)
    responses: list[str] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def query(
        self,
        sys: str,
        user: str,
        log_name: str | None = None,
        config: Any = None,
    ) -> str:
        self.calls.append((sys, user))
        if not self.responses:
            raise AssertionError("LLM appelé sans réponse stub disponible")
        return self.responses.pop(0)


@dataclass
class _FakePhase:
    """Phase minimale satisfaisant les surfaces utilisées par le worker."""

    name: str = "fake"
    content_checks: tuple[Any, ...] = ()
    payload_type: type[_FakePayload] = _FakePayload

    def chunk_source(self, chunk: _FakeChunk) -> ChunkSource:
        return _FakeSource(texts={0: "a", 1: "b"})

    def validate_data(
        self, data: dict[int, str], source: ChunkSource
    ) -> list[ValidationFailure[Any]]:
        failures: list[ValidationFailure[Any]] = []
        for c in self.content_checks:
            failures.extend(c.run(data, source))
        return failures

    def get_llm_config(self, chunk: Any, ctx: Any) -> None:
        return None

    def save_item_builder(self, chunk: Any, data: Any) -> Any:
        # SaveItem stub minimal
        return ("save", chunk.index, dict(data))


# ---------- Helpers ----------


@pytest.fixture(autouse=True)
def reset_commun_context():
    """Dégèle `CommunContext` entre les tests.

    Le worker lit `llm` et `target_language` sur ce singleton gelé ; chaque
    test doit donc pouvoir le reconfigurer.
    """
    yield
    type.__setattr__(CommunContext, "_frozen", False)
    type.__setattr__(CommunContext, "_assigned_fields", set())


def _freeze_context(llm: _FakeLLM) -> None:
    """Gèle `CommunContext` avec le LLM fake ; les autres champs sont muets."""
    CommunContext(
        llm=llm,  # type: ignore[arg-type]
        book=Mock(),
        html_pages=[],
        chapters=Mock(),
        glossary=Mock(),
        store_manager=Mock(),
        target_language="fr",
    )


def _make_worker(
    phase: _FakePhase, llm: _FakeLLM
) -> tuple[
    UnifiedValidationWorker,
    ValidationQueue[dict[int, str]],
    SaveQueue[Any, Any],
]:
    # `UnifiedValidationWorker` n'est plus générique : c'est la spécialisation
    # concrète `ValidationWorker[LineIndexed]`. `LineIndexed` étant un NewType
    # sur `dict[int, str]`, les fakes restent valides au runtime.
    _freeze_context(llm)
    vq: ValidationQueue[dict[int, str]] = ValidationQueue(maxsize=10)
    sq: SaveQueue[Any, Any] = SaveQueue(maxsize=10)
    worker = UnifiedValidationWorker(
        validation_queue=vq,
        save_queue=sq,
        phase=phase,  # type: ignore[arg-type]
        stop_event=threading.Event(),
    )
    return worker, vq, sq


def _make_item(
    data: dict[int, str], attempt: int = 1
) -> ValidationItem[dict[int, str]]:
    from ebook_translator.pipeline.context import ChunkContext

    return ValidationItem[dict[int, str]](
        chunk=_FakeChunk(index=42),  # type: ignore[arg-type]
        chunk_info=ChunkContext(
            phase_name="fake",  # type: ignore[arg-type]
            chunk_index=42,
            previous_chunk=None,
        ),
        data=data,
        attempt=attempt,
    )


# ---------- Scénarios ----------


class TestUnifiedWorker:
    def test_t1_success_no_failures_skips_llm(self) -> None:
        phase = _FakePhase(content_checks=(_FakeCheck(),))
        llm = _FakeLLM(responses=[])
        worker, vq, sq = _make_worker(phase, llm)

        item = _make_item({0: "T0", 1: "T1"})
        vq.put(item)
        # `run()` compose `_process` puis `_save` ; on reproduit la paire.
        data = worker._process(item)  # pyright: ignore[reportPrivateUsage]
        worker._save(item, data)  # pyright: ignore[reportPrivateUsage]

        assert worker.validated_count == 1
        assert worker.rejected_count == 0
        assert llm.calls == []  # zéro appel LLM
        assert sq.qsize() == 1

    def test_t1_fail_t2_success_via_merge(self) -> None:
        phase = _FakePhase(
            content_checks=(_FakeCheck(max_attempts=3, expected_indices=(0, 1)),)
        )
        # T1 fournit ligne 0 ; ligne 1 manque ; LLM retry renvoie ligne 1.
        llm = _FakeLLM(
            responses=["<1/>T1"],
        )
        worker, vq, sq = _make_worker(phase, llm)

        item = _make_item({0: "T0"})
        vq.put(item)
        # `run()` compose `_process` puis `_save` ; on reproduit la paire.
        data = worker._process(item)  # pyright: ignore[reportPrivateUsage]
        worker._save(item, data)  # pyright: ignore[reportPrivateUsage]

        assert worker.validated_count == 1
        assert worker.rejected_count == 0
        assert len(llm.calls) == 1
        # data accumulée = {0: "T0", 1: "T1"} → save_item appelé avec ce dict
        save_item = sq.get(timeout=0.1)
        assert save_item == ("save", 42, {0: "T0", 1: "T1"})

    def test_max_attempts_exhausted_drops_lines_and_saves(self) -> None:
        # max_attempts=1 = 1 retry max pour LINES_MISSING.
        # T1 manque ligne 1 ; le retry ne corrige rien → budget épuisé.
        # Sémantique nouvelle : drop des indices renoncés + save partiel.
        phase = _FakePhase(
            content_checks=(_FakeCheck(max_attempts=1, expected_indices=(0, 1)),)
        )
        llm = _FakeLLM(responses=[""])
        worker, vq, sq = _make_worker(phase, llm)

        item = _make_item({0: "T0"})
        vq.put(item)
        # `run()` compose `_process` puis `_save` ; on reproduit la paire.
        data = worker._process(item)  # pyright: ignore[reportPrivateUsage]
        worker._save(item, data)  # pyright: ignore[reportPrivateUsage]

        assert worker.validated_count == 1
        assert worker.rejected_count == 0
        # Save partiel : ligne 0 conservée, ligne 1 jamais traduite.
        save_item = sq.get(timeout=0.1)
        assert save_item == ("save", 42, {0: "T0"})

    def test_budget_independent_per_error_type(self) -> None:
        """Une failure d'un type ne consomme pas le budget d'un autre type.

        Scénario : T1 manque la ligne 1 (LINES_MISSING budget=1) ; le
        retry corrige la ligne 1 mais introduit une nouvelle failure
        d'un autre type (FRAGMENT_COUNT_MISMATCH, budget=1). Cette
        seconde failure doit pouvoir déclencher SON propre retry, alors
        qu'avec un compteur partagé `attempt` on serait déjà à 2/2.
        """

        @dataclass
        class _FragmentCheck:
            error_type: ErreursType = ErreursType.FRAGMENT_COUNT_MISMATCH
            retry_strategy: RetryStrategy = RetryStrategy.NORMAL_ONLY
            max_attempts: int = 1
            failed_once: list[bool] = field(default_factory=lambda: [False])

            def run(
                self, data: dict[int, str], source: ChunkSource
            ) -> list[ValidationFailure[Any]]:
                # Émet UNE failure FRAGMENT à la première observation où
                # toutes les lignes sont présentes ; ensuite, plus rien.
                if 0 in data and 1 in data and not self.failed_once[0]:
                    self.failed_once[0] = True
                    return [
                        ValidationFailure[Any](
                            error_type=self.error_type,
                            msg="frag",
                            ctx={
                                "line": 0,
                                "expected_pairs": 1,
                                "actual_pairs": 0,
                            },
                            relevant_indices=frozenset({0}),
                        )
                    ]
                return []

        lines = _FakeCheck(max_attempts=1, expected_indices=(0, 1))
        frag = _FragmentCheck()
        phase = _FakePhase(content_checks=(lines, frag))
        llm = _FakeLLM(
            responses=[
                # Retry LINES_MISSING : fournit la ligne 1
                "<1/>T1",
                # Retry FRAGMENT_COUNT_MISMATCH : corrige (peu importe quoi
                # tant que validate passe ensuite)
                "<0/>T0_fixed</>frag",
            ]
        )
        worker, vq, _ = _make_worker(phase, llm)

        item = _make_item({0: "T0"})
        vq.put(item)
        # `run()` compose `_process` puis `_save` ; on reproduit la paire.
        data = worker._process(item)  # pyright: ignore[reportPrivateUsage]
        worker._save(item, data)  # pyright: ignore[reportPrivateUsage]

        assert worker.validated_count == 1
        assert worker.rejected_count == 0
        assert len(llm.calls) == 2  # 2 retries indépendants
