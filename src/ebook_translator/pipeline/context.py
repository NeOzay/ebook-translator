"""
Contextes de données pour le système de phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from ebooklib.epub import EpubBook, EpubHtml

from ebook_translator.frozen_static import FrozenStatic, link_to
from ebook_translator.glossary import Glossary
from ebook_translator.llm.llm import LLM
from ebook_translator.pipeline.base import PhaseName
from ebook_translator.pipeline.store_manager import StoreManager
from ebook_translator.segmentation.chapter import Chapters
from ebook_translator.segmentation.chunk import ChunkProtocol

if TYPE_CHECKING:
    # Cycle : le pool dépend de `CommunContext` (défini ici) au runtime.
    # Cette annotation ne sert qu'au typage.
    from ebook_translator.validation import ValidationWorkerPool


@dataclass
class PhaseStats:
    """
    Statistiques d'exécution d'une phase.

    Collectées par PhaseExecutor pendant l'exécution.
    """

    phase_name: str
    """Nom de la phase"""

    chunks_total: int = 0
    """Nombre total de chunks à traiter"""

    chunks_processed: int = 0
    """Nombre de chunks traités (cache + nouveaux)"""

    chunks_from_cache: int = 0
    """Nombre de chunks récupérés depuis le cache"""

    chunks_translated: int = 0
    """Nombre de chunks nouvellement traduits"""

    chunks_validated: int = 0
    """Nombre de chunks validés avec succès"""

    chunks_rejected: int = 0
    """Nombre de chunks rejetés après validation"""

    duration_seconds: float = 0.0
    """Durée totale d'exécution en secondes"""

    def rejection_rate(self) -> float:
        """Calcule le taux de rejet."""
        if self.chunks_processed == 0:
            return 0.0
        return self.chunks_rejected / self.chunks_processed

    def cache_hit_rate(self) -> float:
        """Calcule le taux de cache hit."""
        if self.chunks_total == 0:
            return 0.0
        return self.chunks_from_cache / self.chunks_total

    def __str__(self) -> str:
        return (
            f"PhaseStats(phase='{self.phase_name}', "
            f"total={self.chunks_total}, "
            f"cache={self.chunks_from_cache}, "
            f"translated={self.chunks_translated}, "
            f"validated={self.chunks_validated}, "
            f"rejected={self.chunks_rejected}, "
            f"duration={self.duration_seconds:.1f}s)"
        )


class CommunContext(FrozenStatic):
    llm: ClassVar[LLM]
    book: ClassVar[EpubBook]
    html_pages: ClassVar[list[EpubHtml]]
    chapters: ClassVar[Chapters]
    glossary: ClassVar[Glossary]
    store_manager: ClassVar[StoreManager]
    target_language: ClassVar[str]

    if TYPE_CHECKING:

        def __init__(
            self,
            *,
            llm: LLM,
            book: EpubBook,
            html_pages: list[EpubHtml],
            chapters: Chapters,
            glossary: Glossary,
            store_manager: StoreManager,
            target_language: str,
            _freeze: bool = True,
        ):
            pass


@link_to(CommunContext)
class PhaseContext(CommunContext):
    """
    Contexte global d'une phase.

    Passé aux hooks before_phase() et after_phase().
    Contient toutes les informations et ressources nécessaires pour l'exécution.
    """

    name: PhaseName

    validation_pool: ValidationWorkerPool
    """Pool de validation pour traiter les traductions"""

    previous_phases: dict[PhaseName, PhaseStats] = field(
        default_factory=dict[PhaseName, PhaseStats]
    )
    """Statistiques des phases précédentes (clé: nom de phase)"""

    def get_previous_stats(self, phase_name: PhaseName) -> PhaseStats | None:
        """
        Récupère les stats d'une phase précédente.

        Args:
            phase_name: Nom de la phase

        Returns:
            PhaseStats si la phase a été exécutée, None sinon
        """
        return self.previous_phases.get(phase_name)


@link_to(CommunContext)
class ChunkContext(CommunContext):
    """
    Contexte d'un chunk individuel.

    Passé aux hooks before_chunk(), after_chunk(), et render_prompt().
    Contient les informations nécessaires pour traiter un chunk spécifique.
    """

    phase_name: PhaseName
    """Nom de la phase en cours"""

    chunk_index: int
    """Index du chunk dans la segmentation"""

    previous_chunk: ChunkProtocol | None
    """Chunk précédent (est None si premier chunk ou chunk traité en parallèle)"""
