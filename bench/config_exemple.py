"""
Exemple de configuration de banc d'essais.

Copier ce fichier, l'adapter, puis lancer :

    uv run python -m ebook_translator.bench bench/mon_essai.py

Ce script compare deux températures sur les phases de traduction, en figeant
l'analyse littéraire : elle est calculée une fois par le run d'amorçage puis
servie depuis le cache à toutes les variantes. Sans ce partage, chaque variante
repartirait d'une analyse différente et l'écart observé sur les traductions ne
serait plus imputable à la température seule.
"""

from pathlib import Path

from ebook_translator.bench import BenchSuite, CorpusOptions, RunEnv, Seed, Variant
from ebook_translator.llm.clients.deepseek import Deepseek, DeepseekModels
from ebook_translator.pipeline.base import PhaseName
from ebook_translator.pipeline.builder import (
    LLMBuilder,
    PhasesBuilder,
    PipelineBuilder,
)
from ebook_translator.translation.language import Language

EPUB = Path("books/The Yellow Wallpaper.epub")


def pipeline(
    env: RunEnv,
    model: DeepseekModels,
    temperature: float,
) -> PipelineBuilder:
    """Construit le pipeline d'une variante.

    Les trois chemins du `RunEnv` sont relayés tels quels : c'est ce qui isole
    la variante (cache, glossaire exporté, EPUB produit). Le harness refuse de
    lancer un pipeline qui les ignore.

    Args:
        env: Emplacements imposés à la variante.
        model: Modèle DeepSeek à employer.
        temperature: Température d'échantillonnage.

    Returns:
        Le builder prêt à être exécuté.
    """
    return (
        PipelineBuilder()
        .epub(env.epub)
        .output(env.output)
        .cache_dir(env.cache_dir)
        .language(Language.FRENCH)
        .llm(
            LLMBuilder()
            .default_client(
                Deepseek(
                    model,
                    thinking=False,
                    config={"temperature": temperature, "max_tokens": 15000},
                )
            )
            .glossary_max_terms(25)
        )
        .phases(
            PhasesBuilder()
            .add_literary_analysis(max_tokens=5000)
            .add_glossary_generation()
            .add_initial_translation(max_tokens=2000)
        )
        .workers(2)
    )


suite = BenchSuite(
    epub=EPUB,
    language=Language.FRENCH,
    # Le seed calcule l'analyse littéraire une fois pour toutes. Sa propre
    # température n'a d'importance que pour cette phase.
    seed=Seed(
        build=lambda env: pipeline(env, DeepseekModels.FLASH, 0.5),
        phases=(PhaseName.LITERARY_ANALYSIS,),
    ),
    variants=[
        Variant(
            id="t05",
            params={"model": "deepseek-flash", "temperature": 0.5},
            build=lambda env: pipeline(env, DeepseekModels.FLASH, 0.5),
        ),
        Variant(
            id="t10",
            params={"model": "deepseek-flash", "temperature": 1.0},
            build=lambda env: pipeline(env, DeepseekModels.FLASH, 1.0),
        ),
    ],
    corpus=CorpusOptions(max_fragments=60),
)
