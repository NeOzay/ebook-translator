"""Banc d'essais : effet d'un glossaire prérempli sur la phase glossaire.

Ce banc répond à une question que le pipeline ne permettait pas de poser :
**comment le modèle se comporte-t-il quand le glossaire n'est pas vide ?**

La phase glossaire n'apprend qu'une émission à la fois, et le facteur de masse
`w / (w + 2)` impose cinq émissions unanimes pour qu'un terme atteigne la
confiance haute. Un run à froid passe donc l'essentiel du livre avec un
glossaire encore instable : les trois groupes de
`common/glossary_existing_block.jinja` — validés, à arbitrer, émergents — ne
sont réellement peuplés qu'à la fin, quand il ne reste plus grand-chose à
extraire. Le préremplissage les remplit dès le premier chunk.

**Phase glossaire seule.** Ni analyse littéraire ni traduction : la question
porte sur la sélection des termes, et `ebook-audit` lit le cache glossaire sans
le moindre appel LLM. Ajouter les phases aval triplerait le coût sur un livre
de 22 Mo sans rien apporter à cette question. Par conséquent, pas de run
d'amorçage non plus — il n'y a aucune phase à partager, et la phase comparée ne
doit jamais l'être.

Deux variantes, seule la garniture initiale du glossaire change :

- `froid` — glossaire vide, comportement de référence.
- `preremp` — glossaire prérempli par `bench/seeds/chillin_vol01.toml`.

Ce qu'on regarde dans le rapport : la part de termes réémis alors qu'ils sont
présentés comme validés, la stabilité des propositions face à celles déjà
pondérées, et le volume total extrait.

Lancement :

    uv run ebook-bench bench/config_glossaire_seed.py

Variante contrôlée : pour cibler un cas précis, éditer le seed — chaque terme
y est placé dans le groupe voulu sans dépendre d'un run antérieur.
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

SERIE = "Chillin' in Another World With Level 2 Super Cheat Powers"
EPUB = Path(f"books/{SERIE} - Volume 01 [J-Novel Club][Premium].epub")

SEED = Path("bench/seeds/chillin_vol01.toml")
"""Préremplissage contrôlé, dérivé de la terminologie du tome lui-même.

Le plan prévoyait le glossaire d'un tome voisin, perdu avec le corpus de la
session 2. Un seed déclaratif le remplace : il place 36 termes dans les trois
groupes — 11 validés, 10 à arbitrer, 15 émergents — tous vérifiés présents
dans le texte, faute de quoi ils ne seraient jamais réinjectés.

Ce que le banc mesure s'en trouve déplacé : l'effet d'un glossaire garni sur
la sélection des termes, et non plus la situation de production où le tome
suivant hérite du précédent. Les conflits du groupe « à arbitrer » sont posés
à la main sur des termes dont le français admet plusieurs rendus, là où un
glossaire appris les aurait produits de lui-même.

Charge mesurée sur le tome : 44 blocs de 8000 caractères, médiane de 10 termes
réinjectés par bloc, 18 au plus — avant l'apport des termes appris en cours de
run, qui s'y ajoutent.
"""


def pipeline(env: RunEnv, prerempli: bool) -> PipelineBuilder:
    """Construit le pipeline d'une variante.

    Les trois chemins du `RunEnv` sont relayés tels quels : c'est ce qui isole
    la variante (cache, glossaire exporté, EPUB produit). Le seed reste en
    lecture seule — le pipeline exporte le sien dans le workspace.

    Args:
        env: Emplacements imposés à la variante.
        prerempli: Partir du glossaire prérempli plutôt que de rien.

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
        .workers(2)
    )
    return builder.glossary_seed(SEED) if prerempli else builder


suite = BenchSuite(
    epub=EPUB,
    language=Language.FRENCH,
    variants=[
        Variant(
            id="froid",
            params={"glossaire_initial": "vide"},
            build=lambda env: pipeline(env, prerempli=False),
        ),
        Variant(
            id="preremp",
            params={
                "glossaire_initial": "seed 36 termes (11 validés / 10 arbitrer / 15 émergents)"
            },
            build=lambda env: pipeline(env, prerempli=True),
        ),
    ],
    # Seuls les glossaires de revue sont comparés : le run ne produit ni
    # traduction ni analyse, les deux autres sections seraient vides.
    corpus=CorpusOptions(translation=False, analysis=False),
)
