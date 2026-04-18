"""
Builder pattern hiérarchique pour configurer et exécuter le pipeline de traduction.

Exemple d'utilisation :
    stats = (
        PipelineBuilder()
        .epub("input.epub")
        .output("output.epub")
        .language("français")
        .llm(
            LLMBuilder()
            .model("deepseek-chat")
            .reasoning("deepseek-reasoner")
            .url("https://api.deepseek.com")
            .temperature(0.7)
        )
        .phases(
            PhasesBuilder()
            .add_literary_analysis()
            .add_initial_translation(max_tokens=2000)
            .add_refinement()
        )
        .workers(4)
        .run()
    )
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from ..htmlpage import BilingualFormat
from ..llm import LLM
from ..llm.llm_config import LLMConfig
from ..pipeline.phases import (
    GlossaryPhase,
    InitialTranslationPhase,
    LiteraryAnalysisPhase,
    RefinementPhase,
)
from .base import PhaseProtocol
from .pipeline import PhaseName, PhaseStats, Pipeline

if TYPE_CHECKING:
    from ..glossary import Glossary


def _skip_none(**overrides: Any) -> dict[str, Any]:
    """Retourne uniquement les overrides explicitement fournis (non-None)."""
    return {k: v for k, v in overrides.items() if v is not None}


class LLMBuilder:
    """Builder pour configurer un LLM.

    Example:
        >>> llm = LLMBuilder().model("deepseek-chat").reasoning("deepseek-reasoner").url("...").build()
    """

    def __init__(self) -> None:
        self._model_name: str | None = None
        self._reasoning_name: str | None = None
        self._url: str | None = None
        self._api_key: str | None = None
        self._prompt_dir: str | None = None
        self._temperature: float | None = None
        self._max_retries: int | None = None
        self._retry_delay: float | None = None
        self._glossary_max_terms: int | None = None

    def model(self, name: str) -> Self:
        """Nom du modèle principal (ex: 'deepseek-chat').

        Args:
            name: Identifiant du modèle LLM principal.

        Returns:
            self pour chaînage.
        """
        self._model_name = name
        return self

    def reasoning(self, name: str) -> Self:
        """Nom du modèle de raisonnement pour les retries avancés.

        Args:
            name: Identifiant du modèle de raisonnement (ex: 'deepseek-reasoner').

        Returns:
            self pour chaînage.
        """
        self._reasoning_name = name
        return self

    def url(self, base_url: str) -> Self:
        """URL de base de l'API LLM.

        Args:
            base_url: URL de l'endpoint API (ex: 'https://api.deepseek.com').

        Returns:
            self pour chaînage.
        """
        self._url = base_url
        return self

    def api_key(self, key: str) -> Self:
        """Clé API. Si non fournie, lue depuis la variable d'environnement API_KEY.

        Args:
            key: Clé d'authentification API.

        Returns:
            self pour chaînage.
        """
        self._api_key = key
        return self

    def prompt_dir(self, directory: str) -> Self:
        """Répertoire des templates Jinja2 (défaut: 'template').

        Args:
            directory: Chemin vers le répertoire de templates.

        Returns:
            self pour chaînage.
        """
        self._prompt_dir = directory
        return self

    def temperature(self, t: float) -> Self:
        """Température d'échantillonnage du LLM (défaut: 0.5).

        Args:
            t: Valeur entre 0.0 (déterministe) et 1.0 (créatif).

        Returns:
            self pour chaînage.
        """
        self._temperature = t
        return self

    def max_retries(self, n: int) -> Self:
        """Nombre maximum de retries API en cas d'erreur réseau (défaut: 3).

        Args:
            n: Nombre de tentatives.

        Returns:
            self pour chaînage.
        """
        self._max_retries = n
        return self

    def retry_delay(self, seconds: float) -> Self:
        """Délai initial entre les retries API en secondes (défaut: 1.0).

        Args:
            seconds: Délai de base (multiplié exponentiellement à chaque retry).

        Returns:
            self pour chaînage.
        """
        self._retry_delay = seconds
        return self

    def glossary_max_terms(self, n: int) -> Self:
        """Nombre maximum de termes du glossaire envoyés au LLM par requête (défaut: 25).

        Args:
            n: Nombre de termes.

        Returns:
            self pour chaînage.
        """
        self._glossary_max_terms = n
        return self

    def build(self) -> LLM:
        """Construit l'instance LLM.

        Returns:
            Instance LLM configurée.

        Raises:
            ValueError: Si model, reasoning ou url ne sont pas définis.
        """
        if self._model_name is None:
            raise ValueError("LLMBuilder: .model() requis")
        if self._reasoning_name is None:
            raise ValueError("LLMBuilder: .reasoning() requis")
        if self._url is None:
            raise ValueError("LLMBuilder: .url() requis")

        return LLM(
            **_skip_none(
                model_name=self._model_name,
                reasoning_name=self._reasoning_name,
                url=self._url,
                api_key=self._api_key,
                prompt_dir=self._prompt_dir,
                temperature=self._temperature,
                max_retries=self._max_retries,
                retry_delay=self._retry_delay,
                glossary_max_terms=self._glossary_max_terms,
            )
        )


class PhasesBuilder:
    """Builder pour sélectionner et configurer les phases du pipeline.

    Example:
        >>> phases = PhasesBuilder().add_literary_analysis().add_initial_translation().add_refinement().build()
    """

    def __init__(self) -> None:
        self._phases: list[PhaseProtocol] = []

    def add_literary_analysis(
        self,
        max_tokens: int | None = None,
        llm_config: LLMConfig | None = None,
    ) -> PhasesBuilder:
        """Ajoute la Phase 0 : analyse littéraire du livre avant traduction.

        Les valeurs non fournies utilisent les defaults de LiteraryAnalysisPhase.

        Args:
            max_tokens: Tokens maximum par chunk de chapitre.
            overlap_ratio: Ratio de chevauchement entre chunks.
            llm_config: Overrides LLM pour cette phase (ex: temperature, max_tokens).
                Note: use_json_mode est toujours forcé à True par cette phase.

        Returns:
            self pour chaînage.
        """
        self._phases.append(
            LiteraryAnalysisPhase(
                **_skip_none(
                    max_tokens=max_tokens,
                    llm_config=llm_config,
                )
            )
        )
        return self

    def add_glossary_generation(
        self, max_tokens: int | None = None, llm_config: LLMConfig | None = None
    ) -> Self:
        self._phases.append(
            GlossaryPhase(
                **_skip_none(
                    llm_config=llm_config,
                    max_tokens=max_tokens,
                )
            )
        )
        return self

    def add_initial_translation(
        self,
        max_tokens: int | None = None,
        overlap_ratio: float | None = None,
        max_workers: int | None = None,
        llm_config: LLMConfig | None = None,
    ) -> Self:
        """Ajoute la Phase 1 : traduction initiale en parallèle.

        Les valeurs non fournies utilisent les defaults de InitialTranslationPhase.

        Args:
            max_tokens: Tokens maximum par chunk.
            overlap_ratio: Ratio de chevauchement entre chunks.
            max_workers: Nombre de workers parallèles.
            llm_config: Overrides LLM pour cette phase (ex: temperature, use_reasoning).

        Returns:
            self pour chaînage.
        """
        self._phases.append(
            InitialTranslationPhase(
                **_skip_none(
                    max_tokens=max_tokens,
                    overlap_ratio=overlap_ratio,
                    max_workers=max_workers,
                    llm_config=llm_config,
                )
            )
        )
        return self

    def add_refinement(
        self,
        max_tokens: int | None = None,
        overlap_ratio: float | None = None,
        llm_config: LLMConfig | None = None,
    ) -> Self:
        """Ajoute la Phase 2 : affinage séquentiel avec glossaire.

        Requiert que la Phase 1 (add_initial_translation) soit ajoutée avant.
        Les valeurs non fournies utilisent les defaults de RefinementPhase.

        Args:
            max_tokens: Tokens maximum par chunk.
            overlap_ratio: Ratio de chevauchement.
            llm_config: Overrides LLM pour cette phase (ex: temperature, use_reasoning).

        Returns:
            self pour chaînage.
        """
        self._phases.append(
            RefinementPhase(
                **_skip_none(
                    max_tokens=max_tokens,
                    overlap_ratio=overlap_ratio,
                    llm_config=llm_config,
                )
            )
        )
        return self

    def build(self) -> list[PhaseProtocol]:
        """Construit la liste de phases.

        Returns:
            Liste ordonnée des phases configurées.

        Raises:
            ValueError: Si aucune phase n'a été ajoutée.
        """
        if not self._phases:
            raise ValueError("PhasesBuilder: au moins une phase requise")
        return list(self._phases)


class PipelineBuilder:
    """Builder principal pour configurer et exécuter le pipeline de traduction.

    Example:
        >>> stats = (
        ...     PipelineBuilder()
        ...     .epub("input.epub")
        ...     .output("output.epub")
        ...     .language("français")
        ...     .llm(LLMBuilder().model("deepseek-chat").reasoning("deepseek-reasoner").url("..."))
        ...     .phases(PhasesBuilder().add_initial_translation().add_refinement())
        ...     .run()
        ... )
    """

    def __init__(self) -> None:
        self._epub_path: Path | None = None
        self._output_epub: Path | None = None
        self._target_language: str | None = None
        self._llm_builder: LLMBuilder | None = None
        self._phases_builder: PhasesBuilder | None = None
        self._num_validation_workers: int | None = 2
        self._cache_dir: Path | None = None
        self._max_retries: int | None = 3
        self._glossary: Glossary | None = None
        self._bilingual_format: BilingualFormat | None

    def epub(self, path: str | Path) -> Self:
        """Chemin vers l'EPUB source.

        Args:
            path: Chemin vers le fichier EPUB à traduire.

        Returns:
            self pour chaînage.
        """
        self._epub_path = path if isinstance(path, Path) else Path(path)
        return self

    def output(self, path: str | Path) -> Self:
        """Chemin de sortie de l'EPUB traduit.

        Args:
            path: Chemin du fichier EPUB de sortie.

        Returns:
            self pour chaînage.
        """
        self._output_epub = path if isinstance(path, Path) else Path(path)
        return self

    def language(self, target: str) -> Self:
        """Langue cible de la traduction.

        Args:
            target: Nom de la langue cible (ex: 'français', 'english').

        Returns:
            self pour chaînage.
        """
        self._target_language = target
        return self

    def llm(self, builder: LLMBuilder) -> Self:
        """Configuration du LLM via un LLMBuilder.

        Args:
            builder: Instance de LLMBuilder configurée.

        Returns:
            self pour chaînage.
        """
        self._llm_builder = builder
        return self

    def phases(self, builder: PhasesBuilder) -> Self:
        """Configuration des phases via un PhasesBuilder.

        Args:
            builder: Instance de PhasesBuilder configurée.

        Returns:
            self pour chaînage.
        """
        self._phases_builder = builder
        return self

    def workers(self, n: int) -> Self:
        """Nombre de workers de validation parallèles (défaut: 2).

        Args:
            n: Nombre de workers.

        Returns:
            self pour chaînage.
        """
        self._num_validation_workers = n
        return self

    def cache_dir(self, path: str | Path) -> Self:
        """Répertoire de cache pour les traductions intermédiaires.

        Si non fourni, créé automatiquement à côté de l'EPUB source.

        Args:
            path: Chemin du répertoire de cache.

        Returns:
            self pour chaînage.
        """
        self._cache_dir = path if isinstance(path, Path) else Path(path)
        return self

    def max_retries(self, n: int) -> Self:
        """Nombre maximum de retries de validation par chunk (défaut: 3).

        Args:
            n: Nombre de tentatives.

        Returns:
            self pour chaînage.
        """
        self._max_retries = n
        return self

    def glossary(self, glossary: "Glossary") -> Self:
        """Glossaire pré-rempli à utiliser. Créé automatiquement si non fourni.

        Args:
            glossary: Instance Glossary pré-configurée.

        Returns:
            self pour chaînage.
        """
        self._glossary = glossary
        return self

    def bilingual_format(self, fmt: BilingualFormat) -> Self:
        """Format de rendu bilingue de l'EPUB de sortie (défaut: SEPARATE_TAG).

        Args:
            fmt: BilingualFormat.SEPARATE_TAG, INLINE ou DISABLE.

        Returns:
            self pour chaînage.
        """
        self._bilingual_format = fmt
        return self

    def build(self) -> tuple[Pipeline, dict[str, object]]:
        """Construit l'instance Pipeline et les paramètres de run().

        Returns:
            Tuple (pipeline, run_kwargs) prêt à appeler pipeline.run(**run_kwargs).

        Raises:
            ValueError: Si epub, output, language, llm ou phases ne sont pas définis.
        """
        if self._epub_path is None:
            raise ValueError("PipelineBuilder: .epub() requis")
        if self._output_epub is None:
            raise ValueError("PipelineBuilder: .output() requis")
        if self._target_language is None:
            raise ValueError("PipelineBuilder: .language() requis")
        if self._llm_builder is None:
            raise ValueError("PipelineBuilder: .llm() requis")
        if self._phases_builder is None:
            raise ValueError("PipelineBuilder: .phases() requis")

        llm = self._llm_builder.build()
        phases = self._phases_builder.build()

        pipeline = Pipeline(
            **_skip_none(
                llm=llm,
                epub_path=self._epub_path,
                phases=phases,
                cache_dir=self._cache_dir,
                num_validation_workers=self._num_validation_workers,
            )
        )

        run_kwargs: dict[str, object] = _skip_none(
            **{
                "target_language": self._target_language,
                "output_epub": self._output_epub,
                "max_retries": self._max_retries,
                "bilingual_format": self._bilingual_format,
            }
        )
        if self._glossary is not None:
            run_kwargs["glossary"] = self._glossary

        return pipeline, run_kwargs

    def run(self) -> dict[PhaseName, PhaseStats]:
        """Construit le pipeline et lance l'exécution complète.

        Returns:
            Statistiques par phase.

        Raises:
            ValueError: Si la configuration est incomplète.
        """
        pipeline, run_kwargs = self.build()
        return pipeline.run(**run_kwargs)  # type: ignore[arg-type]
