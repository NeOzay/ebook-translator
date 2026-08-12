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
            .default_client(Deepseek(DeepseekModels.FLASH, thinking=False))
            .glossary_max_terms(25)
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

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Concatenate, Self, TypedDict

from ..htmlpage import BilingualFormat
from ..llm import LLM
from ..llm.clients.client import ClientProviderProtocol
from ..llm.llm import DEFAULT_RATE_LIMIT_BUDGET
from ..llm.rate_limit import RateLimiter, provider_key_for
from ..llm.template_renderers import DEFAULT_PROMPT_DIR
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


class RunArgs(TypedDict):
    """Arguments de `Pipeline.run`, tels que `PipelineBuilder.build` les résout.

    Typé plutôt que `dict[str, object]` : `pipeline.run(**run_args)` est alors
    vérifié par basedpyright, là où le dictionnaire imposait un
    `ignore[arg-type]` au builder comme au banc d'essais.
    """

    target_language: str
    output_epub: Path
    bilingual_format: BilingualFormat
    glossary: "Glossary | None"


def _mirrors[**P](
    phase_cls: Callable[P, PhaseProtocol],
) -> Callable[
    [Callable[..., "PhasesBuilder"]],
    Callable[Concatenate["PhasesBuilder", P], "PhasesBuilder"],
]:
    """Aligne la signature publique d'un `add_*` sur celle de sa phase.

    La méthode décorée ne porte plus que sa docstring : le décorateur lui
    substitue un corps qui délègue à `PhasesBuilder.add`, et lui donne le type
    du `__init__` de `phase_cls`. Les defaults ne sont donc jamais recopiés dans
    le builder, et basedpyright vérifie les arguments — ce qu'un déballage
    d'overrides typé `dict[str, Any]` empêchait (dette n°2, quatre bugs).

    Les champs `field(init=False)` de la phase sont absents du miroir, sans
    traitement particulier : ils ne sont pas dans son `__init__`.

    Args:
        phase_cls: Classe de phase dont la signature sert de modèle.

    Returns:
        Décorateur retypant la méthode sur `phase_cls.__init__`.

    Example:
        >>> class _Doc:  # doctest: +SKIP
        ...     @_mirrors(InitialTranslationPhase)
        ...     def add_initial_translation(self) -> "PhasesBuilder":
        ...         '''Ajoute la Phase 1.'''
        ...         ...
    """

    def decorate(
        documented: Callable[..., "PhasesBuilder"],
    ) -> Callable[Concatenate["PhasesBuilder", P], "PhasesBuilder"]:
        def adder(self: "PhasesBuilder", *args: Any, **kwargs: Any) -> "PhasesBuilder":
            return self.add(phase_cls, *args, **kwargs)

        # Attributs recopiés à la main plutôt que par `functools.wraps` : celui-ci
        # pose aussi `__wrapped__`, que `inspect.signature` suit jusqu'au stub
        # documenté — elle annoncerait alors `(self)`, soit aucun argument. Sans
        # lui, elle annonce `(self, *args, **kwargs)` : moins précis que le typage
        # statique, mais exact. Publier la vraie signature de la phase n'est pas
        # possible ici : `inspect.signature(phase_cls)` lève `NameError`, les
        # annotations de `PhaseBase` n'étant pas résolvables à l'exécution
        # (`PhaseContext` est importé sous `TYPE_CHECKING`).
        adder.__name__ = documented.__name__
        adder.__qualname__ = documented.__qualname__
        adder.__doc__ = documented.__doc__
        return adder

    return decorate


class LLMBuilder:
    """Builder pour configurer un LLM.

    Le choix du modèle, du mode raisonnement et des paramètres
    d'échantillonnage relève du client (`ClientProviderProtocol`), pas du
    builder : chaque provider expose sa propre enum de modèles et sa propre
    URL de base. Le builder ne porte que les options de `LLM` lui-même.

    Example:
        >>> from ebook_translator.llm.clients.deepseek import Deepseek, DeepseekModels
        >>> llm = (
        ...     LLMBuilder()
        ...     .default_client(Deepseek(DeepseekModels.FLASH, thinking=False))
        ...     .glossary_max_terms(25)
        ...     .build()
        ... )
    """

    # Defaults alignés sur `LLM.__init__` (llm/llm.py) : les porter ici plutôt
    # que de passer des `None` permet à basedpyright de vérifier l'appel.
    def __init__(self) -> None:
        self._client: ClientProviderProtocol[Any, Any] | None = None
        self._prompt_dir: str = DEFAULT_PROMPT_DIR
        self._max_retries: int = 3
        self._retry_delay: float = 1.0
        self._glossary_max_terms: int = 25
        self._rate_limit: float | None = None
        self._rate_limit_budget: float = DEFAULT_RATE_LIMIT_BUDGET

    def default_client(self, provider: ClientProviderProtocol[Any, Any]) -> Self:
        """Client LLM déjà configuré (modèle, thinking, température).

        Args:
            provider: Instance de client, par exemple
                `Deepseek(DeepseekModels.FLASH, thinking=False)`.

        Returns:
            self pour chaînage.
        """
        self._client = provider
        return self

    def prompt_dir(self, directory: str) -> Self:
        """Répertoire des templates Jinja2 (défaut: ceux du package `template`).

        Args:
            directory: Chemin vers le répertoire de templates.

        Returns:
            self pour chaînage.
        """
        self._prompt_dir = directory
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

    def rate_limit(self, per_minute: float) -> Self:
        """Plafonne le débit d'appels au provider (défaut : aucun plafond).

        Le plafond est partagé par tous les threads du pipeline — ceux de
        `PhaseExecutor` comme ceux du pool de validation — **et** par les autres
        processus visant le même provider, via un fichier de créneau. C'est ce
        qui permet à un banc, dont chaque variante est un sous-processus, de ne
        pas saturer l'API au changement de variante.

        Le quota d'un provider s'exprime souvent en requêtes par seconde :
        multiplier par 60. `mistral-large-2512` annonce 0,07 req/s, soit 4,2
        appels par minute — à ce régime, augmenter `.workers()` n'accélère
        rien, le plafond étant atteint bien avant le parallélisme.

        Args:
            per_minute: Nombre maximal d'appels par minute, strictement positif.
                Flottant accepté, l'arrondi fausserait les quotas les plus bas.

        Returns:
            self pour chaînage.

        Example:
            >>> from ebook_translator.llm.clients.mistral import Mistral
            >>> builder = LLMBuilder().default_client(Mistral()).rate_limit(4.2)
        """
        self._rate_limit = per_minute
        return self

    def rate_limit_budget(self, seconds: float) -> Self:
        """Temps d'attente accordé aux rejets de débit sur un appel (défaut: 120 s).

        Distinct de `max_retries`, qui compte les erreurs réseau : un 429 ne
        consomme pas de tentative, il consomme du temps.

        Args:
            seconds: Budget total d'attente par appel.

        Returns:
            self pour chaînage.
        """
        self._rate_limit_budget = seconds
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
            ValueError: Si le client n'est pas défini.
        """
        if self._client is None:
            raise ValueError("LLMBuilder: .default_client() requis")

        # Le limiteur est construit ici, pas au `rate_limit()` : la clé de
        # partage se déduit du client, qui peut être déclaré après le plafond.
        limiter = (
            RateLimiter(self._rate_limit, provider_key_for(self._client))
            if self._rate_limit is not None
            else None
        )

        return LLM(
            client=self._client,
            prompt_dir=self._prompt_dir,
            max_retries=self._max_retries,
            retry_delay=self._retry_delay,
            glossary_max_terms=self._glossary_max_terms,
            rate_limiter=limiter,
            rate_limit_budget=self._rate_limit_budget,
        )


class PhasesBuilder:
    """Builder pour sélectionner et configurer les phases du pipeline.

    Example:
        >>> phases = PhasesBuilder().add_literary_analysis().add_initial_translation().add_refinement().build()
    """

    def __init__(self) -> None:
        self._phases: list[PhaseProtocol] = []

    def add[**P](
        self,
        phase_cls: Callable[P, PhaseProtocol],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> PhasesBuilder:
        """Ajoute une phase quelconque, construite avec les arguments donnés.

        Chemin d'exécution des `add_*`, et point d'extension pour une phase
        maison : les arguments sont vérifiés contre le `__init__` de
        `phase_cls`.

        Args:
            phase_cls: Classe de phase à instancier.
            *args: Arguments positionnels du constructeur de la phase.
            **kwargs: Arguments nommés du constructeur de la phase.

        Returns:
            self pour chaînage.

        Example:
            >>> PhasesBuilder().add(RefinementPhase, max_tokens=400)  # doctest: +SKIP
        """
        self._phases.append(phase_cls(*args, **kwargs))
        return self

    @_mirrors(LiteraryAnalysisPhase)
    def add_literary_analysis(self) -> PhasesBuilder:
        """Ajoute la Phase 0 : analyse littéraire du livre avant traduction.

        Signature miroir de `LiteraryAnalysisPhase`. Elle n'expose que
        `max_tokens` et `llm` : `overlap_ratio` et `head_tail_balance` y sont
        `field(init=False)`, la phase fixant le chevauchement à 0.0 (un
        chapitre entier par chunk).

        La sortie structurée est portée par le schéma `AnalyseChapter` via
        Instructor, pas par un argument d'ici.

        Returns:
            self pour chaînage.

        Example:
            >>> PhasesBuilder().add_literary_analysis(max_tokens=5000)  # doctest: +SKIP
        """
        ...  # corps fourni par `_mirrors`

    @_mirrors(GlossaryPhase)
    def add_glossary_generation(self) -> PhasesBuilder:
        """Ajoute la phase glossaire : extraction des termes avant traduction.

        Signature miroir de `GlossaryPhase` : `max_tokens`, `overlap_ratio`,
        `head_tail_balance` et `llm` (voir `PhaseBase` pour leur sémantique).
        Les valeurs omises sont les defaults de la phase.

        Returns:
            self pour chaînage.

        Example:
            >>> PhasesBuilder().add_glossary_generation(overlap_ratio=0.25)  # doctest: +SKIP
        """
        ...  # corps fourni par `_mirrors`

    @_mirrors(InitialTranslationPhase)
    def add_initial_translation(self) -> PhasesBuilder:
        """Ajoute la Phase 1 : traduction initiale en parallèle.

        Signature miroir de `InitialTranslationPhase` : tout champ de la phase
        se passe en argument nommé, et les valeurs omises sont les defaults de
        la phase — jamais des copies portées ici.

        Options courantes (voir `PhaseBase` pour leur sémantique) :
        `max_tokens`, `overlap_ratio`, `head_tail_balance`, `max_workers`, et
        `llm` pour des overrides LLM propres à la phase (une `LLMConfig` ou un
        client, qui remplace alors le client par défaut).

        Returns:
            self pour chaînage.

        Example:
            >>> PhasesBuilder().add_initial_translation(max_tokens=2000)  # doctest: +SKIP
        """
        ...  # corps fourni par `_mirrors`

    @_mirrors(RefinementPhase)
    def add_refinement(self) -> PhasesBuilder:
        """Ajoute la Phase 2 : affinage séquentiel avec glossaire.

        Requiert que la Phase 1 (`add_initial_translation`) soit ajoutée avant.

        Signature miroir de `RefinementPhase` : `max_tokens`, `overlap_ratio`,
        `head_tail_balance` et `llm` (voir `PhaseBase`). `max_workers` n'y
        figure pas — la phase est séquentielle et le fixe à 1.

        Returns:
            self pour chaînage.

        Example:
            >>> PhasesBuilder().add_initial_translation().add_refinement()  # doctest: +SKIP
        """
        ...  # corps fourni par `_mirrors`

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
        ...     .llm(LLMBuilder().default_client(Deepseek(DeepseekModels.FLASH)))
        ...     .phases(PhasesBuilder().add_initial_translation().add_refinement())
        ...     .run()
        ... )
    """

    def __init__(self) -> None:
        self._epub_path: Path | None = None
        self._output_epub: Path | None = None
        self._epub_genre: str | None = None
        self._target_language: str | None = None
        self._llm_builder: LLMBuilder | None = None
        self._phases_builder: PhasesBuilder | None = None
        # Defaults portés ici plutôt que filtrés à l'appel : `Pipeline(...)` et
        # `Pipeline.run(...)` sont appelés explicitement, donc vérifiés.
        self._num_validation_workers: int = 2
        self._cache_dir: Path | None = None
        self._bilingual_format: BilingualFormat = BilingualFormat.SEPARATE_TAG
        self._glossary: Glossary | None = None
        self._glossary_seed: Path | None = None

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

    def genre(self, genre: str) -> Self:
        """Genre littéraire du livre (ex: 'fantasy', 'science-fiction').

        Args:
            genre: Genre du livre, utilisé pour guider l'analyse littéraire.

        Returns:
            self pour chaînage.
        """
        self._epub_genre = genre
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

    def glossary(self, glossary: "Glossary") -> Self:
        """Glossaire pré-rempli à utiliser. Créé automatiquement si non fourni.

        Args:
            glossary: Instance Glossary pré-configurée.

        Returns:
            self pour chaînage.
        """
        self._glossary = glossary
        return self

    def glossary_seed(self, path: str | Path) -> Self:
        """Fichier TOML préremplissant le glossaire.

        Le seed s'applique au glossaire fourni par `glossary()` s'il y en a un,
        sinon à un glossaire neuf. La résolution a lieu au `build()`, donc
        l'ordre des deux appels est indifférent — un glossaire importé d'un
        tome précédent peut être complété par un seed ciblé, et inversement.

        Args:
            path: Chemin du fichier de seed (voir `ebook_translator.glossary_seed`).

        Returns:
            self pour chaînage.

        Example:
            >>> PipelineBuilder().glossary_seed("bench/seeds/exemple.toml")  # doctest: +SKIP
        """
        self._glossary_seed = path if isinstance(path, Path) else Path(path)
        return self

    def _build_glossary(self) -> Glossary | None:
        """Résout le glossaire de départ du run.

        Import local : `glossary_seed` tire `glossary`, que ce module ne
        charge qu'en annotation.

        Returns:
            Le glossaire prérempli, ou `None` si le run part à froid.

        Raises:
            FileNotFoundError: Si le fichier de seed n'existe pas.
            ValueError: Si le fichier de seed est mal formé.
        """
        if self._glossary_seed is None:
            return self._glossary

        from ..glossary import Glossary
        from ..glossary_seed import apply_seed

        # `is None` et non `or` : `Glossary` définit `__len__`, donc un
        # glossaire fourni mais encore vide serait remplacé sans bruit.
        base = Glossary() if self._glossary is None else self._glossary
        return apply_seed(base, self._glossary_seed)

    def bilingual_format(self, fmt: BilingualFormat) -> Self:
        """Format de rendu bilingue de l'EPUB de sortie (défaut: SEPARATE_TAG).

        Args:
            fmt: BilingualFormat.SEPARATE_TAG, INLINE ou DISABLE.

        Returns:
            self pour chaînage.
        """
        self._bilingual_format = fmt
        return self

    def build(self) -> tuple[Pipeline, RunArgs]:
        """Construit l'instance Pipeline et les paramètres de run().

        Returns:
            Tuple (pipeline, run_args) prêt à appeler pipeline.run(**run_args).

        Raises:
            ValueError: Si epub, output, language, llm ou phases ne sont pas
                définis, ou si le fichier de seed est mal formé.
            FileNotFoundError: Si le fichier de seed n'existe pas.
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
        if self._epub_genre is not None:
            llm.renderer.set_genre(
                self._epub_genre
            )  # Configure le genre pour les prompts

        phases = self._phases_builder.build()

        pipeline = Pipeline(
            llm=llm,
            epub_path=self._epub_path,
            phases=phases,
            cache_dir=self._cache_dir,
            num_validation_workers=self._num_validation_workers,
        )

        run_args: RunArgs = {
            "target_language": self._target_language,
            "output_epub": self._output_epub,
            "bilingual_format": self._bilingual_format,
            "glossary": self._build_glossary(),
        }

        return pipeline, run_args

    def run(self) -> dict[PhaseName, PhaseStats]:
        """Construit le pipeline et lance l'exécution complète.

        Returns:
            Statistiques par phase.

        Raises:
            ValueError: Si la configuration est incomplète.
        """
        pipeline, run_args = self.build()
        return pipeline.run(**run_args)
