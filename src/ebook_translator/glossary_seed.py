"""Préremplissage déclaratif d'un `Glossary`.

Le glossaire ne stocke pas des traductions mais des **distributions** de
propositions, et la confiance qui en découle décide de ce que le prompt de la
phase glossaire montre au modèle. Exercer cette sélection demande donc un
glossaire déjà peuplé — or il faut cinq émissions unanimes pour qu'un terme
atteigne la confiance haute, et trois pour qu'il soit réinjecté avec ses
propositions. Sur un livre court, aucun terme n'y parvient ; sur un livre long,
attendre l'état voulu coûte un run complet et ne permet pas de cibler un cas
précis.

Ce module comble l'écart : un fichier TOML place chaque terme dans l'état
souhaité, sans le moindre appel LLM.

Le fichier décrit une **intention**, pas des poids. Les trois niveaux
correspondent exactement aux trois groupes de `glossary_existing_block.jinja` :

| `niveau`   | Groupe du prompt        | Ce que le modèle voit           |
| ---------- | ----------------------- | ------------------------------- |
| `valide`   | Termes validés          | le terme, à ne pas réémettre    |
| `arbitrer` | Termes à arbitrer       | les propositions et leurs poids |
| `emergent` | Termes déjà extraits    | la forme seule                  |

Example:
    >>> glossaire = load_seed(Path("bench/seeds/exemple.toml"))
    >>> PipelineBuilder().glossary(glossaire)  # doctest: +SKIP
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal, cast, get_args

from ebook_translator.glossary import (
    DEFAULT_MIN_REINJECTION_WEIGHT,
    Glossary,
    converged_weight,
)
from template.phase.glossary_models import (
    GLOSSARY_SEXES_AUTORISES,
    GLOSSARY_TYPES_AUTORISES,
    GlossaryEntrySexe,
    GlossaryEntryType,
    LLMTermeGlossary,
)

SeedNiveau = Literal["valide", "arbitrer", "emergent"]
"""État visé pour un terme, exprimé par le groupe du prompt qui doit l'accueillir."""

SEED_TABLE = "entree"
"""Nom de la table répétée du fichier TOML (`[[entree]]`)."""

_NIVEAUX: frozenset[str] = frozenset(get_args(SeedNiveau))


def poids_pour_niveau(niveau: str) -> int:
    """Nombre d'émissions unanimes plaçant un terme dans le groupe visé.

    Seule porte de validation du champ `niveau` : le paramètre est une chaîne
    quelconque parce que la valeur vient d'un fichier. Les poids sont dérivés
    des seuils du glossaire plutôt que codés en dur — ils suivent donc
    `converged_weight` et `DEFAULT_MIN_REINJECTION_WEIGHT` si ces seuils bougent.

    Args:
        niveau: État visé, tel que lu dans le fichier de seed.

    Returns:
        Le poids à appliquer.

    Raises:
        ValueError: Si le niveau est inconnu.

    Example:
        >>> poids_pour_niveau("emergent")
        1
    """
    match niveau:
        case "valide":
            return converged_weight()
        case "arbitrer":
            return DEFAULT_MIN_REINJECTION_WEIGHT
        case "emergent":
            return 1
        case _:
            raise ValueError(
                f"niveau `{niveau}` inconnu (attendu : {', '.join(sorted(_NIVEAUX))})"
            )


def _exiger_str(entree: dict[str, object], champ: str, position: str) -> str:
    """Lit un champ textuel obligatoire.

    Args:
        entree: Table TOML de l'entrée.
        champ: Nom du champ attendu.
        position: Localisation de l'entrée, pour le message d'erreur.

    Returns:
        La valeur du champ.

    Raises:
        ValueError: Si le champ est absent ou n'est pas une chaîne.
    """
    valeur = entree.get(champ)
    if not isinstance(valeur, str) or not valeur:
        raise ValueError(f"{position} : champ `{champ}` manquant ou non textuel")
    return valeur


def _lire_type(entree: dict[str, object], position: str) -> GlossaryEntryType:
    """Lit et valide la catégorie du terme.

    Args:
        entree: Table TOML de l'entrée.
        position: Localisation de l'entrée, pour le message d'erreur.

    Returns:
        La catégorie validée.

    Raises:
        ValueError: Si la catégorie n'est pas une valeur autorisée.
    """
    valeur = _exiger_str(entree, "type", position)
    if valeur not in GLOSSARY_TYPES_AUTORISES:
        autorises = ", ".join(sorted(GLOSSARY_TYPES_AUTORISES))
        raise ValueError(
            f"{position} : type `{valeur}` inconnu (attendu : {autorises})"
        )
    return valeur


def _lire_sexe(entree: dict[str, object], position: str) -> GlossaryEntrySexe:
    """Lit et valide le genre grammatical du terme.

    Args:
        entree: Table TOML de l'entrée.
        position: Localisation de l'entrée, pour le message d'erreur.

    Returns:
        Le genre validé.

    Raises:
        ValueError: Si le genre n'est pas une valeur autorisée.
    """
    valeur = _exiger_str(entree, "sexe", position)
    if valeur not in GLOSSARY_SEXES_AUTORISES:
        autorises = ", ".join(sorted(GLOSSARY_SEXES_AUTORISES))
        raise ValueError(
            f"{position} : sexe `{valeur}` inconnu (attendu : {autorises})"
        )
    return valeur


def _lire_propositions(
    entree: dict[str, object], position: str
) -> list[tuple[str, int]] | None:
    """Lit les propositions pondérées d'un terme, si l'entrée en déclare.

    Args:
        entree: Table TOML de l'entrée.
        position: Localisation de l'entrée, pour le message d'erreur.

    Returns:
        Les couples `(traduction, poids)`, ou `None` si le champ est absent.

    Raises:
        ValueError: Si la forme du champ n'est pas une liste de couples
            `[texte, entier strictement positif]`.
    """
    brut = entree.get("propositions")
    if brut is None:
        return None
    if not isinstance(brut, list) or not brut:
        raise ValueError(f"{position} : `propositions` doit être une liste non vide")

    propositions: list[tuple[str, int]] = []
    for couple in cast(list[object], brut):
        match couple:
            case [str() as traduction, int() as poids] if traduction and poids > 0:
                propositions.append((traduction, poids))
            case _:
                raise ValueError(
                    f"{position} : proposition {couple!r} invalide "
                    "(attendu : [traduction, poids entier > 0])"
                )
    return propositions


def _appliquer_entree(glossary: Glossary, entree: dict[str, object], rang: int) -> None:
    """Applique une entrée du fichier de seed au glossaire.

    Args:
        glossary: Glossaire à peupler, modifié sur place.
        entree: Table TOML de l'entrée.
        rang: Position de l'entrée dans le fichier, pour les messages d'erreur.

    Raises:
        ValueError: Si l'entrée est mal formée ou combine des champs exclusifs.
    """
    position = f"[[{SEED_TABLE}]] #{rang}"
    terme = _exiger_str(entree, "terme", position)
    position = f"{position} ({terme})"

    terme_type = _lire_type(entree, position)
    sexe = _lire_sexe(entree, position)
    propositions = _lire_propositions(entree, position)
    est_user = bool(entree.get("user", False))

    if est_user:
        if propositions is not None or "niveau" in entree:
            raise ValueError(
                f"{position} : une entrée `user` ne prend ni `niveau` ni "
                "`propositions` — elle est validée, donc sans distribution"
            )
        _ = glossary.add_user_translation(
            terme,
            _exiger_str(entree, "traduction", position),
            sexe=sexe,
            terme_type=terme_type,
        )
        return

    if propositions is None:
        niveau = _exiger_str(entree, "niveau", position)
        try:
            poids = poids_pour_niveau(niveau)
        except ValueError as erreur:
            raise ValueError(f"{position} : {erreur}") from erreur
        propositions = [(_exiger_str(entree, "traduction", position), poids)]
    elif "niveau" in entree:
        raise ValueError(
            f"{position} : `niveau` et `propositions` sont exclusifs — "
            "des propositions pondérées portent déjà leur poids"
        )

    # Passer par `learn()` plutôt que d'écrire les compteurs : c'est la seule
    # voie qui tienne à jour les distributions, les graphies observées et le
    # cache d'entrées résolues, et le seed suit ainsi le format sans dériver.
    for traduction, poids in propositions:
        proposition: LLMTermeGlossary = {
            "terme": terme,
            "type": terme_type,
            "sexe": sexe,
            "proposition_traduction": traduction,
        }
        for _ in range(poids):
            glossary.learn(proposition)


def apply_seed(glossary: Glossary, path: Path) -> Glossary:
    """Applique un fichier de seed à un glossaire existant.

    Les entrées s'ajoutent aux distributions déjà présentes : un glossaire
    importé d'un tome précédent peut donc être complété par un seed ciblé.

    Args:
        glossary: Glossaire à peupler, modifié sur place.
        path: Fichier TOML de seed.

    Returns:
        Le glossaire, pour chaînage.

    Raises:
        FileNotFoundError: Si le fichier n'existe pas.
        ValueError: Si le fichier est mal formé.

    Example:
        >>> apply_seed(Glossary(), Path("bench/seeds/exemple.toml"))  # doctest: +SKIP
    """
    if not path.exists():
        raise FileNotFoundError(f"fichier de seed introuvable : {path}")

    with open(path, "rb") as f:
        données = tomllib.load(f)

    entrees = données.get(SEED_TABLE)
    if not isinstance(entrees, list):
        raise ValueError(
            f"{path} : aucune table `[[{SEED_TABLE}]]` — un seed vide n'a pas de sens"
        )

    for rang, entree in enumerate(cast(list[object], entrees), start=1):
        if not isinstance(entree, dict):
            raise ValueError(f"[[{SEED_TABLE}]] #{rang} : table attendue")
        _appliquer_entree(glossary, cast(dict[str, object], entree), rang)

    return glossary


def load_seed(path: Path) -> Glossary:
    """Construit un glossaire à partir d'un fichier de seed.

    Le glossaire produit garde `cache_path = None`. Le seed n'est pas un cache :
    lui donner ce rôle exposerait le fichier à une réécriture en JSON par un
    `save()` sans argument. Sa protection tient à son extension — le pipeline
    exporte vers `.<stem>_glossary.json`, jamais vers un `.toml`.

    Args:
        path: Fichier TOML de seed.

    Returns:
        Le glossaire peuplé.

    Raises:
        FileNotFoundError: Si le fichier n'existe pas.
        ValueError: Si le fichier est mal formé.

    Example:
        >>> load_seed(Path("bench/seeds/exemple.toml"))  # doctest: +SKIP
    """
    return apply_seed(Glossary(), path)
