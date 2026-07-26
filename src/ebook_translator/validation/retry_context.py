"""Protocol `RetryContext` consommé par les `build` du `RETRY_REGISTRY`.

Surface minimale qu'un caller (typiquement le worker de validation)
expose au registre pour qu'il puisse produire les paramètres typés des
templates de retry. Ne dépend ni de `PhaseBase`, ni du `Chunk` concret —
juste les surfaces génériques (`ChunkProtocol`, `ChunkSource`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..checks.content_check import ChunkSource
    from ..segmentation.chunk import ChunkProtocol


class RetryContext(Protocol):
    """Données environnementales nécessaires à la construction d'un retry.

    `target_language` est nominal côté template ; `chunk` est utilisé pour
    `prepare_for_prompt(indices)` (rendu sélectif des lignes à corriger) ;
    `source` permet `text_at(index)` ; `current_data` est le dernier état
    connu du payload (sortie LLM ou cache) — sert à extraire les lignes
    incorrectes pour les retries `replace`.
    """

    @property
    def target_language(self) -> str: ...
    @property
    def chunk(self) -> ChunkProtocol: ...
    @property
    def source(self) -> ChunkSource: ...
    @property
    def current_data(self) -> dict[int, str]: ...
    @property
    def max_attempts(self) -> int: ...
    @property
    def attempt(self) -> int: ...
