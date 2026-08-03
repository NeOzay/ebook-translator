"""
Banc d'essais comparatif de pipelines.

Exécute N variantes de pipeline sur un même livre, isole leurs caches, partage
les phases figées pour la reproductibilité, et produit un corpus comparatif
anonymisé destiné à être jugé en aveugle par un agent arbitre.

Point d'entrée : `python -m ebook_translator.bench <script_de_config.py>`.
Voir [docs/BENCH.md](../../../docs/BENCH.md).
"""

from .suite import BenchSuite, CorpusOptions, RunEnv, Seed, Variant, load_suite

__all__ = [
    "BenchSuite",
    "CorpusOptions",
    "RunEnv",
    "Seed",
    "Variant",
    "load_suite",
]
