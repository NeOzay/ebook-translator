"""Vérification en conditions réelles du plafond de débit LLM.

Ce banc ne compare pas des prompts : les deux variantes sont **identiques**.
Ce qui est mesuré est le comportement du limiteur quand plusieurs émetteurs se
disputent le même quota — les threads d'une variante (`.workers(2)`) et, si
deux runs sont lancés côte à côte, les sous-processus de variantes.

Le quota visé est celui de `mistral-large-2512` : 0,07 requête par seconde,
soit 4,2 par minute. À ce régime un appel part toutes les ~14 s ; augmenter
`.workers()` n'accélère rien, le plafond mordant avant le parallélisme.

    uv run ebook-bench bench/config_debit_mistral.py --run-id debit_a
    uv run ebook-bench bench/config_debit_mistral.py --run-id debit_b

Attendu : `status: "ok"` et `chunks_processed > 0` dans chaque `result.json`,
et aucun `🚦 Limite de débit` dans `work/<variante>/logs/translation.log`.
"""

from pathlib import Path

from ebook_translator.bench import BenchSuite, CorpusOptions, RunEnv, Variant
from ebook_translator.llm.clients.mistral import Mistral, MistralModels
from ebook_translator.pipeline.builder import (
    LLMBuilder,
    PhasesBuilder,
    PipelineBuilder,
)
from ebook_translator.translation.language import Language

EPUB = Path("books/The Yellow Wallpaper.epub")

RATE_PER_MINUTE = 4.2
"""Quota `mistral-large-2512` : 0,07 req/s. Flottant, l'arrondi le fausserait."""


def pipeline(env: RunEnv) -> PipelineBuilder:
    """Construit le pipeline d'une variante, réduit à la phase glossaire.

    Args:
        env: Emplacements imposés à la variante.

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
                Mistral(
                    MistralModels.LARGE,
                    config={"temperature": 0.5, "max_tokens": 15000},
                )
            )
            .glossary_max_terms(25)
            .rate_limit(RATE_PER_MINUTE)
        )
        .phases(PhasesBuilder().add_glossary_generation())
        # Deux threads sur un quota de 4,2/min : c'est la configuration qui
        # produisait des runs vides déclarés « ok ».
        .workers(2)
    )


suite = BenchSuite(
    epub=EPUB,
    language=Language.FRENCH,
    variants=[
        Variant(id="m1", params={"model": "mistral-large"}, build=pipeline),
        Variant(id="m2", params={"model": "mistral-large"}, build=pipeline),
    ],
    corpus=CorpusOptions(translation=False, analysis=False),
)
