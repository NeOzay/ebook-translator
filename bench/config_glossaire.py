"""Banc de vérification du prompt de glossaire.

Deux variantes sur le même texte, réduites à la seule phase glossaire : ce qui
est mesuré ici n'est pas laquelle traduit le mieux, mais si le prompt révisé
sélectionne au lieu de balayer. L'écart entre les deux modèles dit en outre si
le critère d'admission tient hors de celui sur lequel il a été écrit.

Aucun seed : la phase glossaire ne dépend d'aucune phase amont, et la partager
entre variantes reviendrait à ne rien comparer.

    uv run ebook-bench bench/config_glossaire.py

Chaque cache produit s'audite ensuite séparément :

    uv run ebook-audit "bench/runs/<run_id>/work/<variant>/cache" --phase glossary
"""

from pathlib import Path

from ebook_translator.bench import BenchSuite, CorpusOptions, RunEnv, Variant
from ebook_translator.llm.clients.deepseek import Deepseek, DeepseekModels
from ebook_translator.llm.clients.mistral import Mistral, MistralModels
from ebook_translator.pipeline.builder import (
    LLMBuilder,
    PhasesBuilder,
    PipelineBuilder,
)
from ebook_translator.translation.language import Language

EPUB = Path("books/The Yellow Wallpaper.epub")


def pipeline(env: RunEnv, client: Deepseek | Mistral) -> PipelineBuilder:
    """Construit le pipeline d'une variante, réduit à la phase glossaire.

    Args:
        env: Emplacements imposés à la variante.
        client: Client LLM à interroger.

    Returns:
        Le builder prêt à être exécuté.
    """
    return (
        PipelineBuilder()
        .epub(env.epub)
        .output(env.output)
        .cache_dir(env.cache_dir)
        .language(Language.FRENCH)
        .llm(LLMBuilder().default_client(client).glossary_max_terms(25))
        .phases(PhasesBuilder().add_glossary_generation())
        # `2` est la valeur employée pour les 8 runs de vérification du
        # 2026-08-04, gardée telle quelle pour qu'ils restent reproductibles.
        # Mistral y étrangle le débit une fois sur quatre : le run rend alors
        # zéro chunk sans que rien ne le signale (dette technique n° 10).
        # Passer à 1 avant tout run Mistral dont le résultat doit être fiable.
        .workers(2)
    )


suite = BenchSuite(
    epub=EPUB,
    language=Language.FRENCH,
    variants=[
        Variant(
            id="deepseek",
            params={"model": "deepseek-flash", "temperature": 0.5},
            build=lambda env: pipeline(
                env,
                Deepseek(
                    DeepseekModels.FLASH,
                    thinking=False,
                    config={"temperature": 0.5, "max_tokens": 15000},
                ),
            ),
        ),
        Variant(
            id="mistral",
            params={"model": "mistral-large", "temperature": 0.5},
            build=lambda env: pipeline(
                env,
                Mistral(
                    MistralModels.LARGE,
                    config={"temperature": 0.5, "max_tokens": 15000},
                ),
            ),
        ),
    ],
    # Ni traduction ni analyse à comparer : seul le glossaire est produit.
    corpus=CorpusOptions(translation=False, analysis=False),
)
