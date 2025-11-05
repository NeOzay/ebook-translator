"""
Pipeline en 2 phases pour traduction d'EPUB avec affinage.

Ce package fournit l'infrastructure pour le pipeline de traduction en 2 phases :
- Phase 1 : Traduction initiale (gros blocs 1500 tokens, parallèle)
- Phase 2 : Affinage avec glossaire (petits blocs 300 tokens, séquentiel)
- Correction asynchrone des erreurs via thread dédié

Modules :
- phase1_worker : Worker pour Phase 1 (traduction + apprentissage glossaire)
- phase2_worker : Worker pour Phase 2 (affinage avec glossaire)
- two_phase_pipeline : Orchestrateur principal du pipeline complet
"""

from .phase1_worker import Phase1Worker
from .phase2_worker import Phase2Worker
from .two_phase_pipeline import TwoPhasePipeline

__all__ = ["Phase1Worker", "Phase2Worker", "TwoPhasePipeline"]
