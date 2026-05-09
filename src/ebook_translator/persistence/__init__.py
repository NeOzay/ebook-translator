"""Couche persistance : stratégies de cache `ChunkPersister[M, ChunkT]`.

Les `ChunkPersister` orchestrent le couplage entre :
- un modèle Pydantic (`M`) — la donnée structurée d'une phase,
- un chunk (`ChunkT`) — l'unité de travail,
- un `ByteStore` — la couche octets (filesystem ou mémoire).

Chaque persister implémente une stratégie de cache distincte (par
fichier source pour les phases traduction, par chunk fingerprint pour
Phase 0 / glossaire). Cela découple les modèles (Pydantic purs, dans
`template/`) de la mécanique I/O.
"""

from .chunk_persister import ChunkPersister

__all__ = ["ChunkPersister"]
