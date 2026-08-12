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

from ebook_translator.htmlpage import BilingualFormat
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


class TestRateLimit:
    """Plafond de débit : absent par défaut, explicite sinon.

    Motivé par les 429 Mistral du 2026-08-04, qui vidaient un run de banc sans
    que rien ne le signale.
    """

    @pytest.fixture(autouse=True)
    def _isolated_cache(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        # `build()` crée le répertoire de créneau : sans cette isolation, les
        # tests écriraient dans le cache réel de l'utilisateur.
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    def test_no_limiter_by_default(self, client: Deepseek) -> None:
        llm = LLMBuilder().default_client(client).build()

        assert llm.rate_limiter is None

    def test_rate_limit_builds_a_limiter(self, client: Deepseek) -> None:
        llm = LLMBuilder().default_client(client).rate_limit(30).build()

        assert llm.rate_limiter is not None
        assert llm.rate_limiter.interval == pytest.approx(2.0)

    def test_limiter_key_comes_from_the_client(self, client: Deepseek) -> None:
        llm = LLMBuilder().default_client(client).rate_limit(30).build()

        assert llm.rate_limiter is not None
        assert llm.rate_limiter.state_path.name == "deepseek"

    def test_rate_limit_before_the_client_still_works(self, client: Deepseek) -> None:
        # La clé se déduit du client : l'ordre des appels ne doit pas compter.
        llm = LLMBuilder().rate_limit(30).default_client(client).build()

        assert llm.rate_limiter is not None
        assert llm.rate_limiter.state_path.name == "deepseek"

    def test_fractional_rate_is_supported(self, client: Deepseek) -> None:
        # `mistral-large-2512` : 0,07 req/s, soit 4,2 par minute. Arrondir à 4
        # sous-utiliserait le quota, à 5 le dépasserait.
        llm = LLMBuilder().default_client(client).rate_limit(4.2).build()

        assert llm.rate_limiter is not None
        assert llm.rate_limiter.interval == pytest.approx(60 / 4.2)

    def test_invalid_rate_is_rejected_at_build(self, client: Deepseek) -> None:
        with pytest.raises(ValueError, match="strictement positif"):
            _ = LLMBuilder().default_client(client).rate_limit(0).build()

    def test_budget_default_matches_llm(self, client: Deepseek) -> None:
        built = LLMBuilder().default_client(client).build()

        assert built.rate_limit_budget == LLM(client=client).rate_limit_budget

    def test_budget_is_forwarded(self, client: Deepseek) -> None:
        llm = LLMBuilder().default_client(client).rate_limit_budget(45.0).build()

        assert llm.rate_limit_budget == 45.0


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
    def test_llm_is_accepted(self, method: str) -> None:
        """Le paramètre porte le nom du champ de la phase : `llm`.

        Il s'appelait `llm_config` tant que le builder recopiait les signatures ;
        le miroir de `_mirrors` interdit désormais l'écart entre les deux.
        """
        config = GenericLLMConfig(temperature=0.3)
        phases = getattr(PhasesBuilder(), method)(llm=config).build()

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
    def test_llm_accepts_a_client(self, method: str) -> None:
        """Une phase peut substituer son propre client au client par défaut.

        `LLM.query` remplace `self.client` quand la config reçue *est* un
        `ClientProviderProtocol` — d'où le type élargi sur `llm`.
        """
        client = Deepseek(DeepseekModels.PRO, thinking=True)
        phases = getattr(PhasesBuilder(), method)(llm=client).build()

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

    def test_head_tail_balance_reaches_the_phase(self) -> None:
        """Champ ouvert par le miroir : il n'était exposé par aucun `add_*`."""
        phases = PhasesBuilder().add_refinement(head_tail_balance=0.6).build()

        assert phases[0].head_tail_balance == 0.6

    @pytest.mark.parametrize(
        ("method", "unknown"),
        [
            ("add_literary_analysis", {"overlap_ratio": 0.3}),
            ("add_glossary_generation", {"max_workers": 2}),
            ("add_initial_translation", {"llm_config": None}),
            ("add_refinement", {"max_workers": 2}),
        ],
    )
    def test_unknown_argument_is_rejected(
        self, method: str, unknown: dict[str, object]
    ) -> None:
        """Le miroir refuse ce que la phase n'accepte pas.

        C'est la dette n°2 épinglée côté exécution : basedpyright signale déjà
        ces appels, ce test garantit qu'ils ne passent pas non plus en silence
        si quelqu'un contourne le type-checker. Les cas couverts sont réels —
        `max_workers` sur une phase séquentielle, `overlap_ratio` sur la Phase 0
        qui le fixe à 0.0 (`field(init=False)`), et l'ancien nom `llm_config`.
        """
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            _ = getattr(PhasesBuilder(), method)(**unknown)

    def test_add_accepts_any_phase_class(self) -> None:
        """`add()` est le chemin d'exécution des `add_*` et le point d'extension."""
        phases = PhasesBuilder().add(RefinementPhase, max_tokens=400).build()

        assert isinstance(phases[0], RefinementPhase)
        assert phases[0].max_tokens == 400

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

    def test_build_returns_pipeline_and_run_args(
        self, epub_path: Path, tmp_path: Path
    ) -> None:
        pipeline, run_args = self._complete(epub_path, tmp_path).build()

        assert len(pipeline.phases) == 2
        assert run_args["target_language"] == Language.FRENCH
        assert run_args["output_epub"] == tmp_path / "out.epub"

    def test_run_args_are_complete(self, epub_path: Path, tmp_path: Path) -> None:
        """`run()` fait `pipeline.run(**run_args)` : le contrat est `RunArgs`.

        La conformité des clés à `Pipeline.run` est désormais vérifiée par
        basedpyright — `RunArgs` est un `TypedDict`, plus un `dict[str, object]`.
        Ce test garde trace du contrat côté exécution : les quatre clés sont
        toujours présentes, y compris `glossary` à `None` quand le run part à
        froid, et `bilingual_format` que le builder résout au lieu de l'omettre.
        """
        _, run_args = self._complete(epub_path, tmp_path).build()

        assert set(run_args) == {
            "target_language",
            "output_epub",
            "bilingual_format",
            "glossary",
        }
        assert run_args["glossary"] is None
        assert run_args["bilingual_format"] is BilingualFormat.SEPARATE_TAG

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
