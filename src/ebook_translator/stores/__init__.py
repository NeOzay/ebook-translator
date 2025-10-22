"""
Gestion des stores multiples pour le pipeline en 2 phases.

Ce package fournit:
- MultiStore: Gestionnaire de stores pour initial/refined
- GlossaryStore: Extension d'AutoGlossary pour apprentissage automatique
"""

from .multi_store import MultiStore
from .glossary_store import GlossaryStore

__all__ = ["MultiStore", "GlossaryStore"]
