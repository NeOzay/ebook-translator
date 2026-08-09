"""Banc de fumée : vérifier la mécanique du préremplissage avant d'engager un tome.

Ce banc ne mesure rien. Il tourne sur un extrait d'environ 8 000 caractères —
**un seul chunk de glossaire, donc un appel LLM par variante** — et sert uniquement à
valider la chaîne de bout en bout avant de lancer
`bench/config_glossaire_seed.py` sur un livre de 22 Mo : isolation des
workspaces, écriture du cache, collecte des glossaires de revue, rendu du
rapport.

Un chunk unique ne peut faire converger aucun terme et ne dit rien de la
stabilisation. Ne pas lire son rapport comme un résultat.

Ce qu'il exerce en revanche, et que le banc réel n'exerce pas : les quatre
canaux de réinjection en une fois, via un seed déclaratif — un terme validé
qui ne doit pas être réémis, un conflit à arbitrer, un terme émergent montré
sans sa traduction, et une entrée `user` qui ne passe pas par l'arbitrage. La
sortie du modèle se lit alors directement contre les attendus notés dans
`bench/seeds/smoke.toml`.

Lancement :

    uv run ebook-bench bench/config_glossaire_smoke.py
"""

from pathlib import Path

from ebook_translator.bench import BenchSuite, CorpusOptions, RunEnv, Variant
from ebook_translator.llm.clients.deepseek import Deepseek, DeepseekModels
from ebook_translator.pipeline.builder import (
    LLMBuilder,
    PhasesBuilder,
    PipelineBuilder,
)
from ebook_translator.translation.language import Language

EPUB = Path("books/Chillin Vol 01 - extrait chapitre 3_1.epub")
"""Extrait d'un seul chapitre du tome que fait tourner `config_glossaire_seed`.

Prendre l'extrait dans le livre du banc réel n'est pas un détail de commodité :
les termes du seed doivent figurer dans le texte pour être réinjectés, faute de
quoi les deux variantes reçoivent le même prompt et la fumée ne teste rien.
"""

SEED = Path("bench/seeds/smoke.toml")


def pipeline(env: RunEnv, seed: Path | None) -> PipelineBuilder:
    """Construit le pipeline d'une variante.

    Args:
        env: Emplacements imposés à la variante.
        seed: Fichier de seed, ou `None` pour partir à froid.

    Returns:
        Le builder prêt à être exécuté.
    """
    builder = (
        PipelineBuilder()
        .epub(env.epub)
        .output(env.output)
        .cache_dir(env.cache_dir)
        .language(Language.FRENCH)
        .genre("fantasy")
        .llm(
            LLMBuilder().default_client(
                Deepseek(
                    DeepseekModels.FLASH,
                    thinking=False,
                    config={"temperature": 0.5, "max_tokens": 15000},
                )
            )
        )
        .phases(PhasesBuilder().add_glossary_generation())
        .workers(1)
    )
    return builder.glossary_seed(seed) if seed is not None else builder


suite = BenchSuite(
    epub=EPUB,
    language=Language.FRENCH,
    variants=[
        Variant(
            id="froid",
            params={"glossaire_initial": "vide"},
            build=lambda env: pipeline(env, None),
        ),
        Variant(
            id="seede",
            params={"glossaire_initial": str(SEED)},
            build=lambda env: pipeline(env, SEED),
        ),
    ],
    corpus=CorpusOptions(translation=False, analysis=False),
)
