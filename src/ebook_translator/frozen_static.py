"""
Système de contexte pour pipeline.

- `G` : classe statique (non-instanciée) avec schéma fixe, gelée après l'appel
  à `freeze(G)` ou via le sucre `G(field=value, ..., _freeze=True)`.
- `@local(G)` : décorateur qui transforme une classe `class T(G): ...` en
  dataclass(frozen=True) avec fallback transparent vers G.

Côté typage : l'utilisateur écrit `class FetchStep(G):`, donc BasedPyright voit
naturellement les champs de G accessibles sur les instances. Au runtime, le
décorateur neutralise l'héritage : la classe finale n'hérite pas de G et ne
possède pas sa métaclasse, ce qui évite les interférences avec @dataclass.

Astuce typage pour la classe globale
------------------------------------

Pour avoir l'autocomplétion ET la validation des types sur l'appel
`G(field1=v1, field2=v2, ...)`, déclare une signature `__init__` côté
TYPE_CHECKING dans ta classe globale :

    from typing import TYPE_CHECKING, ClassVar
    from pipeline_context import FrozenStatic

    class CommunContext(FrozenStatic):
        llm: ClassVar[LLM]
        target_language: ClassVar[str]
        glossary: ClassVar[Glossary]

        if TYPE_CHECKING:
            def __init__(
                self,
                *,
                llm: LLM,
                target_language: str,
                glossary: Glossary,
                _freeze: bool = True,
            ) -> None: ...

    # Le checker valide l'appel suivant (autocomplétion + types vérifiés) ;
    # au runtime, _FrozenStaticMeta.__call__ prend la main pour configurer
    # et geler la classe.
    CommunContext(
        llm=my_llm,
        target_language="fr",
        glossary=my_glossary,
    )

Note : BasedPyright en strict-mode peut émettre un warning
`reportMissingSuperCall` sur le stub `__init__` (puisqu'il n'appelle pas
super().__init__()). Comme la signature est purement déclarative, on peut
l'ignorer avec `# pyright: ignore[reportMissingSuperCall]` au-dessus du
`def __init__`.

Cette technique est volontairement laissée au site d'utilisation (et non
fournie automatiquement par FrozenStatic) parce qu'utiliser `dataclass_transform`
sur la métaclasse casserait l'initialisation des classes locales décorées
par `@local(G)` : les champs de G se propageraient comme paramètres requis
de leur init.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import (
    TYPE_CHECKING,
    Any,
    dataclass_transform,
    get_type_hints,
)

# --------------------------------------------------------------------------- #
# Métaclasse pour G : contrôle l'écriture/lecture des attributs *de la classe*
# --------------------------------------------------------------------------- #

# Note : on n'utilise pas @dataclass_transform sur cette métaclasse. Cela
# semblerait pratique pour avoir une autocomplétion sur `G(...)`, mais ça
# casse `class FetchStep(G):` côté typage : les champs de G se propageraient
# comme paramètres requis de l'init de FetchStep. Le compromis retenu est
# d'avoir un G(...) non validé statiquement (seul site de configuration
# dans le programme), au profit d'instances locales correctement typées.


class _FrozenStaticMeta(type):
    """Métaclasse qui implémente le cycle de vie : configuring -> frozen.

    - Pendant la phase de configuration : seuls les champs déclarés via
      annotations peuvent être assignés ; la lecture est interdite.
    - Après `freeze()` : toute écriture lève TypeError ; la lecture est libre.
    """

    def __new__(mcs, name: str, bases: tuple[type, ...], ns: dict[str, Any]) -> type:
        cls = super().__new__(mcs, name, bases, ns)
        try:
            hints = get_type_hints(cls)
        except Exception:
            # Fallback compatible PEP 649 (Python 3.14+).
            hints = inspect.get_annotations(cls)
        # Dans FrozenStatic, toute annotation est un champ — y compris ClassVar.
        # ClassVar est même la déclaration la plus correcte pour ces champs
        # (ce sont des variables de classe, pas d'instance), et permet aux
        # type-checkers stricts d'accepter l'absence de valeur initiale.
        declared = set(hints)
        type.__setattr__(cls, "_declared_fields", frozenset(declared))
        type.__setattr__(cls, "_assigned_fields", set())
        type.__setattr__(cls, "_frozen", False)
        return cls

    def __setattr__(cls, name: str, value: Any) -> None:
        if name.startswith("_"):
            type.__setattr__(cls, name, value)
            return

        if cls._frozen:
            raise TypeError(
                f"{cls.__name__} est gelé : impossible de modifier '{name}'."
            )
        if name not in cls._declared_fields:
            raise TypeError(
                f"{cls.__name__} n'a pas de champ déclaré '{name}'. "
                f"Champs attendus : {sorted(cls._declared_fields)}."
            )
        type.__setattr__(cls, name, value)
        cls._assigned_fields.add(name)

    def __getattribute__(cls, name: str) -> Any:
        # Pas de filtre sur des méthodes publiques : FrozenStatic n'en expose
        # plus aucune (freeze et is_frozen sont des fonctions libres). On
        # garde uniquement le filtre sur les champs déclarés.
        if name.startswith("_"):
            return super().__getattribute__(name)
        declared = super().__getattribute__("_declared_fields")
        if name in declared:
            frozen = super().__getattribute__("_frozen")
            if not frozen:
                raise RuntimeError(
                    f"{cls.__name__} n'est pas encore gelé : "
                    f"lecture de '{name}' interdite avant freeze()."
                )
        return super().__getattribute__(name)

    if not TYPE_CHECKING:
        # __call__ n'est défini qu'au runtime. Côté type-checker, on laisse
        # la signature par défaut de `type.__call__` en place — l'utilisateur
        # passera tout de même par cette méthode au runtime.
        def __call__(cls, **kwargs):
            """Configuration en un appel : `G(field1=v1, field2=v2, _freeze=True)`.

            - Court-circuite l'instanciation : G n'est jamais instancié.
            - `_freeze` (défaut True) : si True, gèle la classe à la fin de
              l'appel (et lève si des champs déclarés manquent).
            - Si la classe est déjà gelée, lève RuntimeError avant toute écriture.
            - Vérifie que chaque kwarg correspond à un champ déclaré (la
              vérification des types est laissée au type-checker, voir la
              technique de signature __init__ dans FrozenStatic).
            """
            if cls._frozen:
                raise RuntimeError(
                    f"{cls.__name__} est déjà gelé : configuration impossible."
                )

            do_freeze = kwargs.pop("_freeze", True)

            # Validation préalable des noms avant la moindre écriture,
            # pour préserver l'atomicité en cas d'erreur.
            unknown = set(kwargs) - cls._declared_fields
            if unknown:
                raise TypeError(
                    f"{cls.__name__} n'a pas de champ déclaré : {sorted(unknown)}. "
                    f"Champs attendus : {sorted(cls._declared_fields)}."
                )

            for name, value in kwargs.items():
                setattr(cls, name, value)

            if do_freeze:
                freeze(cls)


# --------------------------------------------------------------------------- #
# Classe de base pour le singleton statique
# --------------------------------------------------------------------------- #


class FrozenStatic(metaclass=_FrozenStaticMeta):
    """Marker pour les singletons statiques gelés.

    N'expose volontairement aucune méthode publique : les opérations sur la
    classe globale (freeze, is_frozen) sont des fonctions libres du module,
    pour ne pas polluer la complétion des classes locales qui héritent de G
    au sens du typage.

    Configuration
    -------------

    Deux styles équivalents au runtime :

        # Style explicite (typage parfait, plus verbeux)
        G.field1 = v1
        G.field2 = v2
        freeze(G)

        # Style en un appel (sucre syntaxique)
        G(field1=v1, field2=v2)  # _freeze=True par défaut

    Pour que le second style soit aussi typé statiquement (autocomplétion +
    validation des types), déclare une signature `__init__` TYPE_CHECKING
    dans ta classe — voir le docstring du module pour un exemple complet.
    """

    if TYPE_CHECKING:
        # Signature TYPE_CHECKING-only par défaut, qui accepte n'importe quels
        # kwargs. Les sous-classes peuvent la surcharger pour avoir un typage
        # précis sur leur appel `G(...)` (voir docstring du module).
        # Au runtime, c'est `_FrozenStaticMeta.__call__` qui prend la main.
        def __init__(self, **kwargs: Any) -> None: ...


# --------------------------------------------------------------------------- #
# Fonctions libres opérant sur le singleton
# --------------------------------------------------------------------------- #


def freeze(global_cls: type[FrozenStatic]) -> None:
    """Gèle la classe globale après vérification que tous les champs déclarés
    ont été assignés. Toute écriture ultérieure lèvera TypeError."""
    missing = global_cls._declared_fields - global_cls._assigned_fields
    if missing:
        raise RuntimeError(
            f"Impossible de geler {global_cls.__name__} : "
            f"champs non assignés : {sorted(missing)}."
        )
    type.__setattr__(global_cls, "_frozen", True)


def is_frozen(global_cls: type[FrozenStatic]) -> bool:
    """Indique si la classe globale a été gelée."""
    return global_cls._frozen


# --------------------------------------------------------------------------- #
# Décorateur @local(G) : dataclass frozen + fallback vers G
# --------------------------------------------------------------------------- #

if TYPE_CHECKING:
    # Côté checker : @local(G) est vu comme un décorateur identité (renvoie
    # la classe telle quelle). Comme l'utilisateur écrit `class T(G):`,
    # BasedPyright voit naturellement les champs de G + ceux déclarés
    # localement, et `dataclass_transform` lui fait générer un __init__
    # avec les bons paramètres.
    from typing import TypeVar

    _T = TypeVar("_T")

    @dataclass_transform(frozen_default=True)
    def link_to(global_cls: type[FrozenStatic]) -> Callable[[type[_T]], type[_T]]: ...

else:

    @dataclass_transform(frozen_default=True)
    def link_to(global_cls):
        """Décorateur paramétré : @local(G) sur `class T(G): ...` produit une
        dataclass gelée qui n'hérite plus de G au runtime (héritage neutralisé)
        mais conserve un fallback transparent vers G via __getattr__."""

        if not isinstance(global_cls, _FrozenStaticMeta):
            raise TypeError(
                f"local(...) attend une sous-classe de FrozenStatic, "
                f"reçu {global_cls!r}."
            )

        def decorator(cls):
            # Vérifier que la classe hérite bien de global_cls (sinon le typage
            # ne marchera pas correctement et l'intention est ambiguë).
            if global_cls not in cls.__mro__:
                raise TypeError(
                    f"{cls.__name__} doit hériter de {global_cls.__name__} "
                    f"pour être décorée avec @local({global_cls.__name__})."
                )

            # On reconstruit une nouvelle classe SANS héritage de global_cls,
            # pour que @dataclass et la métaclasse de G ne se marchent pas dessus.
            # inspect.get_annotations() renvoie uniquement les annotations
            # *locales* (pas héritées) — c'est exactement ce qu'on veut.
            # Cette API est compatible 3.10+ et gère correctement les
            # annotations lazy de PEP 649 en Python 3.14+.
            local_annotations = inspect.get_annotations(cls)

            # Récupérer les attributs définis dans le corps de cls (valeurs
            # par défaut, méthodes, etc.) — sans les hériter de G.
            local_namespace = {
                k: v
                for k, v in cls.__dict__.items()
                if k not in ("__dict__", "__weakref__", "__annotations__")
            }
            local_namespace["__annotations__"] = local_annotations

            # Bases : on retire tout ce qui descend de FrozenStatic.
            new_bases = tuple(
                b
                for b in cls.__bases__
                if not isinstance(b, _FrozenStaticMeta) and b is not FrozenStatic
            ) or (object,)

            # Préparer __post_init__ AVANT @dataclass.
            original_post_init = cls.__dict__.get("__post_init__")

            def __post_init__(self):
                local_names = {f.name for f in fields(self)}
                global_names = global_cls._declared_fields
                collisions = local_names & global_names
                if collisions:
                    raise TypeError(
                        f"{type(self).__name__} masque des champs de "
                        f"{global_cls.__name__} : {sorted(collisions)}."
                    )
                if original_post_init is not None:
                    original_post_init(self)

            def __getattr__(self, name):
                if name.startswith("_"):
                    raise AttributeError(name)
                if name in global_cls._declared_fields:
                    return getattr(global_cls, name)
                raise AttributeError(
                    f"{type(self).__name__!r} n'a pas d'attribut {name!r} "
                    f"(et {global_cls.__name__} non plus)."
                )

            local_namespace["__post_init__"] = __post_init__
            local_namespace["__getattr__"] = __getattr__

            new_cls = type(cls.__name__, new_bases, local_namespace)
            new_cls.__qualname__ = cls.__qualname__
            new_cls.__module__ = cls.__module__

            return dataclass(frozen=True)(new_cls)

        return decorator
