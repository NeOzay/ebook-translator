"""Tests de non-régression des builders (`pipeline/builder.py`).

Ces builders sont l'API publique de configuration du pipeline, et n'étaient
couverts par aucun test : trois appels y passaient des kwargs inexistants
(`LLM(model_name=...)`, `GlossaryPhase(overrides=...)`, `Phase(llm_config=...)`),
masqués à basedpyright par l'indirection `**_skip_none(...)` typée
`dict[str, Any]`. Chaque défaut ne se manifestait qu'à l'exécution.

Aucun appel réseau : `Deepseek` n'ouvre pas de connexion à la construction, et
seule la construction des objets est vérifiée — pas leur exécution.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ebook_translator.llm import LLM
from ebook_translator.llm.clients.deepseek import Deepseek, DeepseekModels
from ebook_translator.llm.llm_config import GenericLLMConfig
from ebook_translator.pipeline.builder import (
    LLMBuilder,
    PhasesBuilder,
    PipelineBuilder,
)
from ebook_translator.pipeline.phases import (
    GlossaryPhase,
    InitialTranslationPhase,
    LiteraryAnalysisPhase,
    RefinementPhase,
)
from ebook_translator.translation.language import Language


@pytest.fixture(autouse=True)
def _api_key(  # pyright: ignore[reportUnusedFunction]  # fixture autouse
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Évite la lecture du `.env` et le `sys.exit(1)` de `get_api_key`."""
    monkeypatch.setenv("API_KEY", "sk-test-not-a-real-key")


@pytest.fixture
def client() -> Deepseek:
    return Deepseek(DeepseekModels.FLASH, thinking=False)


class TestLLMBuilder:
    def test_build_returns_llm(self, client: Deepseek) -> None:
        llm = LLMBuilder().default_client(client).build()

        assert isinstance(llm, LLM)
        assert llm.client is client

    def test_client_is_required(self) -> None:
        with pytest.raises(ValueError, match=r"\.default_client\(\) requis"):
            _ = LLMBuilder().build()

    def test_defaults_match_llm_signature(self, client: Deepseek) -> None:
        """Les defaults portés par le builder doivent suivre `LLM.__init__`."""
        built = LLMBuilder().default_client(client).build()
        direct = LLM(client=client)

        assert built.max_retries == direct.max_retries
        assert built.retry_delay == direct.retry_delay

    def test_options_are_forwarded(self, client: Deepseek) -> None:
        llm = (
            LLMBuilder()
            .default_client(client)
            .max_retries(7)
            .retry_delay(2.5)
            .glossary_max_terms(3)
            .build()
        )

        assert llm.max_retries == 7
        assert llm.retry_delay == 2.5


class TestPhasesBuilder:
    @pytest.mark.parametrize(
        ("method", "expected"),
        [
            ("add_literary_analysis", LiteraryAnalysisPhase),
            ("add_glossary_generation", GlossaryPhase),
            ("add_initial_translation", InitialTranslationPhase),
            ("add_refinement", RefinementPhase),
        ],
    )
    def test_add_with_defaults(self, method: str, expected: type) -> None:
        phases = getattr(PhasesBuilder(), method)().build()

        assert len(phases) == 1
        assert isinstance(phases[0], expected)

    @pytest.mark.parametrize(
        "method",
        [
            "add_literary_analysis",
            "add_glossary_generation",
            "add_initial_translation",
            "add_refinement",
        ],
    )
    def test_llm_config_is_accepted(self, method: str) -> None:
        """`llm_config` alimente le champ `llm` de la phase, pas un `llm_config`."""
        config = GenericLLMConfig(temperature=0.3)
        phases = getattr(PhasesBuilder(), method)(llm_config=config).build()

        assert phases[0].llm is config  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.parametrize(
        "method",
        [
            "add_literary_analysis",
            "add_glossary_generation",
            "add_initial_translation",
            "add_refinement",
        ],
    )
    def test_llm_config_accepts_a_client(self, method: str) -> None:
        """Une phase peut substituer son propre client au client par défaut.

        `LLM.query` remplace `self.client` quand la config reçue *est* un
        `ClientProviderProtocol` — d'où le type élargi sur `llm_config`.
        """
        client = Deepseek(DeepseekModels.PRO, thinking=True)
        phases = getattr(PhasesBuilder(), method)(llm_config=client).build()

        assert phases[0].llm is client  # pyright: ignore[reportAttributeAccessIssue]

    def test_glossary_accepts_overlap_ratio(self) -> None:
        phases = PhasesBuilder().add_glossary_generation(overlap_ratio=0.25).build()

        assert phases[0].overlap_ratio == 0.25

    def test_overrides_are_forwarded(self) -> None:
        phases = (
            PhasesBuilder()
            .add_initial_translation(max_tokens=2000, overlap_ratio=0.1, max_workers=3)
            .build()
        )
        phase = phases[0]

        assert phase.max_tokens == 2000
        assert phase.overlap_ratio == 0.1
        assert phase.get_worker_count() == 3

    def test_at_least_one_phase_required(self) -> None:
        with pytest.raises(ValueError, match="au moins une phase"):
            _ = PhasesBuilder().build()

    def test_order_is_preserved(self) -> None:
        phases = (
            PhasesBuilder()
            .add_literary_analysis()
            .add_initial_translation()
            .add_refinement()
            .build()
        )

        assert [type(p) for p in phases] == [
            LiteraryAnalysisPhase,
            InitialTranslationPhase,
            RefinementPhase,
        ]


class TestPipelineBuilder:
    @pytest.fixture
    def epub_path(self) -> Path:
        return Path("tests/Saint-Exupery-Le_Petit_Prince.epub")

    def _complete(self, epub_path: Path, tmp_path: Path) -> PipelineBuilder:
        return (
            PipelineBuilder()
            .epub(epub_path)
            .output(tmp_path / "out.epub")
            .language(Language.FRENCH)
            .llm(LLMBuilder().default_client(Deepseek(DeepseekModels.FLASH)))
            .phases(PhasesBuilder().add_initial_translation().add_refinement())
            .cache_dir(tmp_path / "cache")
        )

    def test_build_returns_pipeline_and_run_kwargs(
        self, epub_path: Path, tmp_path: Path
    ) -> None:
        pipeline, run_kwargs = self._complete(epub_path, tmp_path).build()

        assert len(pipeline.phases) == 2
        assert run_kwargs["target_language"] == Language.FRENCH
        assert run_kwargs["output_epub"] == tmp_path / "out.epub"

    def test_run_kwargs_match_pipeline_run_signature(
        self, epub_path: Path, tmp_path: Path
    ) -> None:
        """`run()` fait `pipeline.run(**run_kwargs)` : les clés doivent exister."""
        import inspect

        from ebook_translator.pipeline.pipeline import Pipeline

        _, run_kwargs = self._complete(epub_path, tmp_path).build()
        accepted = set(inspect.signature(Pipeline.run).parameters) - {"self"}

        assert set(run_kwargs) <= accepted

    @pytest.mark.parametrize(
        ("omit", "message"),
        [
            ("epub", r"\.epub\(\) requis"),
            ("output", r"\.output\(\) requis"),
            ("language", r"\.language\(\) requis"),
            ("llm", r"\.llm\(\) requis"),
            ("phases", r"\.phases\(\) requis"),
        ],
    )
    def test_missing_required_field(
        self, epub_path: Path, tmp_path: Path, omit: str, message: str
    ) -> None:
        builder = PipelineBuilder().cache_dir(tmp_path / "cache")
        if omit != "epub":
            _ = builder.epub(epub_path)
        if omit != "output":
            _ = builder.output(tmp_path / "out.epub")
        if omit != "language":
            _ = builder.language(Language.FRENCH)
        if omit != "llm":
            _ = builder.llm(LLMBuilder().default_client(Deepseek(DeepseekModels.FLASH)))
        if omit != "phases":
            _ = builder.phases(PhasesBuilder().add_initial_translation())

        with pytest.raises(ValueError, match=message):
            _ = builder.build()
