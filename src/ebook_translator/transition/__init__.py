"""
Module transition - Transitions entre phases de traduction.

Ce module fournit une abstraction pour définir des transitions entre phases,
permettant de valider et préparer le passage d'une phase à une autre.
"""

from ebook_translator.transition.base import TransitionBase, TransitionContext

__all__ = [
    "TransitionBase",
    "TransitionContext",
]
