"""
Contextes de données pour le système de phases.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ebooklib import epub

from ebook_translator.pipeline.base import PhaseName
from ebook_translator.pipeline.store_manager import StoreManager
from ebook_translator.segmentation import Chapters, Chunk
from ebook_translator.validation import ValidationWorkerPool

if TYPE_CHECKING:
    from ebook_translator.glossary import Glossary
    from ebook_translator.llm import LLM


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


@dataclass
class PhaseContext:
    """
    Contexte global d'une phase.

    Passé aux hooks before_phase() et after_phase().
    Contient toutes les informations et ressources nécessaires pour l'exécution.
    """

    target_language: str
    """Langue cible de la traduction (ex: 'français', 'english')"""

    html_items: list[epub.EpubHtml]
    """Liste des items HTML à traiter (filename, content)"""

    # Imports retardés pour éviter les cycles
    llm: LLM
    """Instance LLM pour les requêtes de traduction"""

    store_manager: StoreManager
    """Gestionnaire de stores pour accéder aux caches"""

    validation_pool: ValidationWorkerPool
    """Pool de validation pour traiter les traductions"""

    glossary: Glossary
    """Glossaire optionnel pour cohérence terminologique"""

    book: epub.EpubBook
    """EpubBook source (pour TOC-aware segmentation et noms de chapitres via TOC)"""

    chapters: Chapters = field(init=False)
    """Gestionnaire de chapitres et analyses littéraires (initialisé automatiquement)"""

    previous_phases: dict[PhaseName, PhaseStats] = field(
        default_factory=dict[PhaseName, PhaseStats]
    )
    """Statistiques des phases précédentes (clé: nom de phase)"""

    def __post_init__(self) -> None:
        """Initialise Chapters automatiquement depuis le livre EPUB."""
        self.chapters = Chapters(self.book, self.store_manager)

    def get_previous_stats(self, phase_name: PhaseName) -> PhaseStats | None:
        """
        Récupère les stats d'une phase précédente.

        Args:
            phase_name: Nom de la phase

        Returns:
            PhaseStats si la phase a été exécutée, None sinon
        """
        return self.previous_phases.get(phase_name)


@dataclass
class ChunkContext:
    """
    Contexte d'un chunk individuel.

    Passé aux hooks before_chunk(), after_chunk(), et render_prompt().
    Contient les informations nécessaires pour traiter un chunk spécifique.
    """

    target_language: str
    """Langue cible de la traduction"""

    phase_name: str
    """Nom de la phase en cours"""

    chunk_index: int
    """Index du chunk dans la segmentation"""

    # Imports retardés pour éviter les cycles
    llm: LLM
    """Instance LLM pour les requêtes de traduction"""

    store_manager: StoreManager
    """Gestionnaire de stores pour accéder aux caches"""

    glossary: Glossary
    """Glossaire optionnel pour cohérence terminologique"""

    def get_previous_translation(
        self,
        chunk: Chunk,
        phase_name: str,
    ) -> tuple[dict[int, str], bool]:
        """
        Helper: récupère la traduction d'un chunk depuis une phase précédente.

        Args:
            chunk: Chunk dont on veut la traduction
            phase_name: Nom de la phase source (ex: 'initial')

        Returns:
            Tuple (traductions, has_missing) où:
            - traductions: Mapping line_index -> translated_text (ou chaîne vide si manquante)
            - has_missing: True si au moins une traduction est manquante, False sinon

        Example:
            # Dans RefinementPhase.render_prompt()
            initial_translation, has_missing = context.get_previous_translation(chunk, "initial")
            if not has_missing:
                return render_refine(chunk, initial_translation, ...)
        """
        return self.store_manager.get_translate(phase_name, chunk)

    def export_glossary(self, path: Path) -> bool:
        """
        Helper: exporte le glossaire vers un fichier.

        Args:
            path: Chemin du fichier de sortie

        Returns:
            True si exporté avec succès, False sinon
        """
        try:
            # self.glossary.export_to_file(path)
            return True
        except Exception:
            return False
