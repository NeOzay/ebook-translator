"""
Modèle de configuration du banc d'essais.

Une suite se déclare dans un script Python que l'utilisateur écrit lui-même et
qui expose une variable `suite: BenchSuite`. Le script garde toute
l'expressivité des builders (`PipelineBuilder`, `LLMBuilder`, `PhasesBuilder`) :
chaque variante fournit une fabrique `(RunEnv) -> PipelineBuilder`, appelée
dans le sous-processus qui exécute cette variante.

Example:
    ```python
    # bench/config_exemple.py
    def base(env: RunEnv, model: DeepseekModels, temperature: float) -> PipelineBuilder:
        return (
            PipelineBuilder()
            .epub(env.epub)
            .output(env.output)
            .cache_dir(env.cache_dir)
            .language(Language.FRENCH)
            .llm(LLMBuilder().default_client(Deepseek(model, config={"temperature": temperature})))
            .phases(PhasesBuilder().add_literary_analysis().add_initial_translation())
        )


    suite = BenchSuite(
        epub=Path("books/The Yellow Wallpaper.epub"),
        seed=Seed(
            build=lambda env: base(env, DeepseekModels.FLASH, 0.5),
            phases=(PhaseName.LITERARY_ANALYSIS,),
        ),
        variants=[
            Variant("t05", {"temperature": 0.5}, lambda env: base(env, DeepseekModels.FLASH, 0.5)),
            Variant("t10", {"temperature": 1.0}, lambda env: base(env, DeepseekModels.FLASH, 1.0)),
        ],
    )
    ```
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ebook_translator.pipeline.base import PhaseName
from ebook_translator.pipeline.builder import PipelineBuilder

SEED_ID = "seed"
"""Identifiant réservé au run d'amorçage : aucune variante ne peut le porter."""

LOGS_DIRNAME = "logs"
"""Nom du répertoire des logs, dans un workspace de variante comme dans un run."""

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
"""Un identifiant sert de nom de répertoire : minuscules, chiffres, `-` et `_`."""


@dataclass(frozen=True)
class RunEnv:
    """Emplacements imposés à une variante par le harness.

    La fabrique d'une variante **doit** relayer ces trois chemins au
    `PipelineBuilder` (`.epub()`, `.output()`, `.cache_dir()`) : c'est ce qui
    isole les variantes les unes des autres. Le runner le vérifie après
    construction et refuse un pipeline qui les ignore.

    Attributes:
        variant_id: Identifiant de la variante (ou `seed` pour l'amorçage).
        epub: EPUB source, vu depuis le workspace de la variante (symlink).
        output: Chemin de l'EPUB traduit à produire.
        cache_dir: Racine du cache de la variante.
        workspace: Répertoire de travail de la variante.
    """

    variant_id: str
    epub: Path
    output: Path
    cache_dir: Path
    workspace: Path

    @property
    def logs_dir(self) -> Path:
        """Répertoire des logs de la variante.

        Le sous-processus s'y redirige avant d'exécuter le pipeline : la trace
        d'une variante reste ainsi dans son workspace, avec son cache et son
        résultat.
        """
        return self.workspace / LOGS_DIRNAME


type PipelineFactory = Callable[[RunEnv], PipelineBuilder]
"""Fabrique appelée dans le sous-processus, juste avant l'exécution."""


@dataclass(frozen=True)
class Variant:
    """Une configuration de pipeline à comparer aux autres.

    Attributes:
        id: Identifiant court, unique dans la suite. Sert de nom de répertoire.
        params: Paramètres décrivant la variante (modèle, température, …).
            Métadonnée pure : elle alimente le manifeste, jamais le corpus
            anonymisé remis à l'arbitre.
        build: Fabrique du `PipelineBuilder`, appelée avec le `RunEnv`.

    Raises:
        ValueError: Si `id` n'est pas un identifiant de répertoire valide ou
            s'il empiète sur l'identifiant réservé du run d'amorçage.
    """

    id: str
    params: Mapping[str, object]
    build: PipelineFactory

    def __post_init__(self) -> None:
        if not _ID_PATTERN.match(self.id):
            raise ValueError(
                f"Variant id invalide : {self.id!r}. Attendu : minuscules, "
                f"chiffres, '-' ou '_', commençant par une lettre ou un chiffre."
            )
        if self.id == SEED_ID:
            raise ValueError(
                f"Variant id {SEED_ID!r} est réservé au run d'amorçage (Seed)."
            )


@dataclass(frozen=True)
class Seed:
    """Run d'amorçage produisant les phases partagées par toutes les variantes.

    Le seed s'exécute en premier, dans son propre workspace. Les stores des
    phases listées dans `phases` sont ensuite copiés dans le cache de chaque
    variante, qui les sert alors depuis le cache — sans appel LLM et avec un
    résultat identique pour toutes. C'est ce qui rend la comparaison
    reproductible quand seules les phases aval varient.

    La fabrique du seed doit déclarer **au moins** les phases partagées ; elle
    peut en déclarer d'autres (leurs stores ne seront simplement pas repris).

    Attributes:
        build: Fabrique du `PipelineBuilder` du run d'amorçage.
        phases: Phases dont le cache est repris par les variantes.

    Raises:
        ValueError: Si `phases` est vide (un seed sans phase partagée ne sert
            à rien : il coûterait un run complet pour rien).
    """

    build: PipelineFactory
    phases: tuple[PhaseName, ...]

    def __post_init__(self) -> None:
        if not self.phases:
            raise ValueError("Seed.phases ne peut pas être vide.")
        if len(set(self.phases)) != len(self.phases):
            raise ValueError(f"Seed.phases contient des doublons : {self.phases}.")


@dataclass(frozen=True)
class CorpusOptions:
    """Réglages de l'extraction du corpus comparatif.

    Attributes:
        translation: Inclure la comparaison fragment à fragment des traductions.
        glossary: Inclure les glossaires exportés par la phase glossaire.
        analysis: Inclure les fiches d'analyse littéraire (Phase 0).
        max_fragments: Plafond de fragments retenus par fichier HTML. `None`
            pour tout garder. Un plafond évite de noyer l'arbitre sur un gros
            livre.
        include_identical: Conserver les fragments traduits à l'identique par
            toutes les variantes. Faux par défaut : ils n'apportent rien au
            jugement et sont de toute façon comptés dans les métriques.
    """

    translation: bool = True
    glossary: bool = True
    analysis: bool = True
    max_fragments: int | None = 120
    include_identical: bool = False


@dataclass(frozen=True)
class BenchSuite:
    """Déclaration complète d'un banc d'essais.

    Attributes:
        epub: EPUB source, commun à toutes les variantes.
        variants: Variantes à comparer (au moins deux : comparer une variante
            à elle-même n'a pas de sens).
        seed: Run d'amorçage optionnel pour les phases partagées.
        language: Langue cible, reportée dans le manifeste à titre de contexte.
            Le réglage effectif reste celui du `PipelineBuilder` de la variante.
        corpus: Réglages d'extraction du corpus comparatif.

    Raises:
        ValueError: Si moins de deux variantes sont déclarées ou si deux
            variantes partagent le même identifiant.
        FileNotFoundError: Si l'EPUB source est introuvable.
    """

    epub: Path
    variants: Sequence[Variant]
    seed: Seed | None = None
    language: str = ""
    corpus: CorpusOptions = field(default_factory=CorpusOptions)

    def __post_init__(self) -> None:
        if len(self.variants) < 2:
            raise ValueError(
                f"BenchSuite : au moins 2 variantes requises, "
                f"{len(self.variants)} déclarée(s)."
            )

        doublons = _duplicates(variant.id for variant in self.variants)
        if doublons:
            raise ValueError(f"Identifiants de variante en double : {doublons}.")

        if not self.epub.exists():
            raise FileNotFoundError(f"EPUB source introuvable : {self.epub}")

    def variant(self, variant_id: str) -> Variant:
        """Récupère une variante par identifiant.

        Args:
            variant_id: Identifiant déclaré dans la suite.

        Returns:
            La variante correspondante.

        Raises:
            KeyError: Si aucune variante ne porte cet identifiant.
        """
        for variant in self.variants:
            if variant.id == variant_id:
                return variant
        raise KeyError(
            f"Variante inconnue : {variant_id!r}. "
            f"Déclarées : {[v.id for v in self.variants]}."
        )

    def factory(self, variant_id: str) -> PipelineFactory:
        """Fabrique de pipeline d'une variante, ou du run d'amorçage.

        Args:
            variant_id: Identifiant de variante, ou `SEED_ID` pour l'amorçage.

        Returns:
            La fabrique à appeler avec le `RunEnv`.

        Raises:
            KeyError: Si l'identifiant est inconnu, ou si `SEED_ID` est demandé
                alors que la suite ne déclare pas de seed.
        """
        if variant_id == SEED_ID:
            if self.seed is None:
                raise KeyError("La suite ne déclare pas de run d'amorçage (seed).")
            return self.seed.build
        return self.variant(variant_id).build

    @property
    def shared_phases(self) -> tuple[PhaseName, ...]:
        """Phases reprises du run d'amorçage, vide s'il n'y en a pas."""
        return self.seed.phases if self.seed is not None else ()


def _duplicates(values: Iterable[str]) -> list[str]:
    """Liste triée des valeurs apparaissant plus d'une fois."""
    vus: set[str] = set()
    doublons: set[str] = set()
    for value in values:
        if value in vus:
            doublons.add(value)
        vus.add(value)
    return sorted(doublons)


def load_suite(config_path: Path | str) -> BenchSuite:
    """Charge la suite déclarée par un script de configuration.

    Le script est importé sous le nom de module `ebook_translator_bench_config`
    et doit exposer une variable `suite` de type `BenchSuite`. L'import est
    fait par chemin (`spec_from_file_location`) : le script n'a pas besoin
    d'être un package installé, ni de vivre dans le `sys.path`.

    Args:
        config_path: Chemin du script de configuration.

    Returns:
        La suite déclarée.

    Raises:
        FileNotFoundError: Si le script n'existe pas.
        AttributeError: Si le script n'expose pas de variable `suite`.
        TypeError: Si `suite` n'est pas une `BenchSuite`.
        ImportError: Si le module ne peut pas être chargé.
    """
    path = Path(config_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Script de configuration introuvable : {path}")

    module_name = "ebook_translator_bench_config"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Impossible de charger le script de configuration : {path}")

    module = importlib.util.module_from_spec(spec)
    # Enregistré avant exécution : un script qui fait des imports relatifs à
    # lui-même, ou une dataclass qui se réfère à son propre module, échouerait
    # sinon à se résoudre.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    suite = getattr(module, "suite", None)
    if suite is None:
        raise AttributeError(
            f"{path} n'expose pas de variable `suite`. "
            f"Attendu : `suite = BenchSuite(...)` au niveau module."
        )
    if not isinstance(suite, BenchSuite):
        raise TypeError(
            f"{path} : `suite` doit être une BenchSuite, reçu {type(suite).__name__}."
        )
    return suite
