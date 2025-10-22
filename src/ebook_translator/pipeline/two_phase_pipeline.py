"""
Orchestrateur principal du pipeline de traduction en 2 phases.

Ce module gère le workflow complet :
- Phase 1 : Traduction initiale (gros blocs 1500 tokens, parallèle)
- Phase 2 : Affinage avec glossaire (petits blocs 300 tokens, séquentiel)
- Thread de correction dédié (erreurs asynchrones)
- Reconstruction EPUB avec fallback refined → initial
"""

from pathlib import Path
from typing import TYPE_CHECKING

from ebooklib import epub

from ..logger import get_logger
from ..stores.multi_store import MultiStore
from ..glossary import Glossary
from ..correction.error_queue import ErrorQueue
from ..correction.correction_worker import CorrectionWorker
from ..segment import Segmentator
from ..translation.epub_handler import (
    copy_epub_metadata,
    extract_html_items_in_spine_order,
    reconstruct_html_item,
)
from .phase1_worker import Phase1Worker
from .phase2_worker import Phase2Worker

if TYPE_CHECKING:
    from ..llm import LLM
    from ..translation.translator import Language

logger = get_logger(__name__)


class TwoPhasePipeline:
    """
    Pipeline de traduction EPUB en 2 phases avec affinage.

    Architecture :
    1. Phase 1 (parallèle) :
       - Segmentation 1500 tokens
       - Traduction initiale
       - Apprentissage glossaire automatique
       - Sauvegarde dans initial_store

    2. Transition :
       - Switch stores (initial → refined)
       - Export glossaire

    3. Phase 2 (séquentiel) :
       - Segmentation 300 tokens
       - Affinage avec glossaire + traduction initiale
       - Sauvegarde dans refined_store

    4. Correction asynchrone :
       - Thread dédié consommant ErrorQueue
       - Retry automatique jusqu'à max_retries
       - Erreurs non-bloquantes

    5. Reconstruction EPUB :
       - Fallback refined → initial → original
       - Métadonnées préservées

    Attributes:
        llm: Instance LLM pour traduction et affinage
        epub_path: Chemin vers l'EPUB source
        cache_dir: Répertoire racine des caches
        multi_store: Gestionnaire initial_store + refined_store
        glossary: Glossary unifié pour cohérence
        error_queue: Queue thread-safe pour erreurs
        correction_worker: Thread daemon de correction

    Example:
        >>> pipeline = TwoPhasePipeline(llm, "book.epub", Path("cache"))
        >>> stats = pipeline.run(Language.FRENCH, "book_fr.epub", phase1_workers=4)
        >>> print(f"Phase 1: {stats['phase1']['translated']}")
        >>> print(f"Phase 2: {stats['phase2']['refined']}")
        >>> print(f"Glossaire: {stats['glossary']['total_terms']} termes")
    """

    def __init__(
        self,
        llm: "LLM",
        epub_path: str | Path,
        cache_dir: str | Path,
    ):
        """
        Initialise le pipeline en 2 phases.

        Args:
            llm: Instance LLM pour traduction et affinage
            epub_path: Chemin vers l'EPUB source
            cache_dir: Répertoire pour caches (initial/, refined/, glossary.json)
        """
        self.llm = llm
        self.epub_path = epub_path if isinstance(epub_path, Path) else Path(epub_path)
        self.cache_dir = cache_dir if isinstance(cache_dir, Path) else Path(cache_dir)

        # Valider que l'EPUB existe
        if not self.epub_path.exists():
            raise FileNotFoundError(f"EPUB source introuvable : {self.epub_path}")

        # Créer cache_dir si nécessaire
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialiser infrastructure
        self.multi_store = MultiStore(self.cache_dir)
        self.glossary = Glossary(cache_path=self.cache_dir / "glossary.json")
        self.error_queue = ErrorQueue(maxsize=100)
        self.correction_worker: CorrectionWorker | None = None

        # Statistiques globales
        self.phase1_stats: dict = {}
        self.phase2_stats: dict = {}
        self.correction_stats: dict = {}

    def run(
        self,
        target_language: "Language | str",
        output_epub: str | Path,
        phase1_workers: int = 4,
        phase1_max_tokens: int = 1500,
        phase2_max_tokens: int = 300,
        correction_timeout: float = 30.0,
    ) -> dict:
        """
        Exécute le pipeline complet de traduction en 2 phases.

        Args:
            target_language: Langue cible (enum Language ou str)
            output_epub: Chemin de sortie pour l'EPUB traduit
            phase1_workers: Nombre de threads parallèles Phase 1 (défaut: 4)
            phase1_max_tokens: Taille max chunks Phase 1 (défaut: 1500)
            phase2_max_tokens: Taille max chunks Phase 2 (défaut: 300)
            correction_timeout: Timeout pour arrêt CorrectionWorker (défaut: 30s)

        Returns:
            Statistiques complètes :
            {
                "phase1": {...},
                "phase2": {...},
                "corrections": {...},
                "glossary": {...},
                "total_duration": float
            }

        Example:
            >>> stats = pipeline.run(
            ...     target_language=Language.FRENCH,
            ...     output_epub="book_fr.epub",
            ...     phase1_workers=4,
            ... )
        """
        import time

        start_time = time.time()

        # Normaliser target_language
        from ..translation.translator import Language

        target_language_str = (
            target_language.value
            if isinstance(target_language, Language)
            else target_language
        )

        output_epub = output_epub if isinstance(output_epub, Path) else Path(output_epub)

        logger.info(f"🚀 Démarrage pipeline 2 phases : {self.epub_path} → {output_epub}")
        logger.info(f"  • Langue cible: {target_language_str}")
        logger.info(f"  • Phase 1: {phase1_max_tokens} tokens, {phase1_workers} workers")
        logger.info(f"  • Phase 2: {phase2_max_tokens} tokens, séquentiel")

        # =====================================================================
        # CHARGEMENT EPUB
        # =====================================================================
        logger.info("📖 Chargement de l'EPUB source...")
        source_book = epub.read_epub(self.epub_path)
        html_items, target_book = extract_html_items_in_spine_order(source_book)
        copy_epub_metadata(source_book, target_book, str(target_language_str))
        logger.info(f"  • {len(html_items)} chapitres extraits")

        # =====================================================================
        # DÉMARRAGE CORRECTION WORKER
        # =====================================================================
        logger.info("🔧 Démarrage du thread de correction...")
        self.correction_worker = CorrectionWorker(
            error_queue=self.error_queue,
            llm=self.llm,
            store=self.multi_store.initial_store,  # Commence avec initial
            target_language=target_language_str,
        )
        self.correction_worker.start()

        try:
            # =================================================================
            # PHASE 1 : TRADUCTION INITIALE (PARALLÈLE)
            # =================================================================
            logger.info("=" * 60)
            logger.info("📝 PHASE 1 : TRADUCTION INITIALE")
            logger.info("=" * 60)

            # Segmentation Phase 1 (gros blocs)
            segmentator_phase1 = Segmentator(html_items, max_tokens=phase1_max_tokens)
            chunks_phase1 = list(segmentator_phase1.get_all_segments())
            logger.info(f"  • {len(chunks_phase1)} chunks créés ({phase1_max_tokens} tokens)")

            # Worker Phase 1
            phase1_worker = Phase1Worker(
                llm=self.llm,
                store=self.multi_store.initial_store,
                glossary=self.glossary,
                error_queue=self.error_queue,
                target_language=target_language_str,
            )

            # Exécuter Phase 1
            self.phase1_stats = phase1_worker.run_parallel(
                chunks=chunks_phase1,
                max_workers=phase1_workers,
            )

            # Statistiques glossaire après Phase 1
            glossary_stats = self.glossary.get_statistics()
            logger.info(f"📚 Glossaire appris: {glossary_stats['total_terms']} termes")

            # =================================================================
            # TRANSITION PHASE 1 → PHASE 2
            # =================================================================
            logger.info("=" * 60)
            logger.info("🔄 TRANSITION PHASE 1 → PHASE 2")
            logger.info("=" * 60)

            # Switch store pour refined
            self.multi_store.switch_to_refined()
            logger.info("  • MultiStore basculé vers refined_store")

            # Switch CorrectionWorker vers refined_store
            self.correction_worker.switch_store(self.multi_store.refined_store)
            logger.info("  • CorrectionWorker basculé vers refined_store")

            # Sauvegarder glossaire
            self.glossary.save()
            logger.info(f"  • Glossaire sauvegardé: {self.cache_dir / 'glossary.json'}")

            # =================================================================
            # PHASE 2 : AFFINAGE AVEC GLOSSAIRE (SÉQUENTIEL)
            # =================================================================
            logger.info("=" * 60)
            logger.info("🎨 PHASE 2 : AFFINAGE AVEC GLOSSAIRE")
            logger.info("=" * 60)

            # Segmentation Phase 2 (petits blocs)
            segmentator_phase2 = Segmentator(html_items, max_tokens=phase2_max_tokens)
            chunks_phase2 = list(segmentator_phase2.get_all_segments())
            logger.info(f"  • {len(chunks_phase2)} chunks créés ({phase2_max_tokens} tokens)")

            # Worker Phase 2
            phase2_worker = Phase2Worker(
                llm=self.llm,
                multi_store=self.multi_store,
                glossary=self.glossary,
                error_queue=self.error_queue,
                target_language=target_language_str,
            )

            # Exécuter Phase 2
            self.phase2_stats = phase2_worker.run_sequential(chunks=chunks_phase2)

            # =================================================================
            # FINALISATION CORRECTIONS
            # =================================================================
            logger.info("=" * 60)
            logger.info("🛑 FINALISATION DES CORRECTIONS")
            logger.info("=" * 60)

            # Arrêter CorrectionWorker proprement
            logger.info(f"  • Attente de fin des corrections (timeout: {correction_timeout}s)...")
            stopped = self.correction_worker.stop(timeout=correction_timeout)

            if not stopped:
                logger.warning(
                    f"⚠️ CorrectionWorker n'a pas pu s'arrêter dans le délai ({correction_timeout}s)"
                )

            # Statistiques corrections
            self.correction_stats = {
                **self.correction_worker.get_statistics(),
                **self.error_queue.get_statistics().__dict__,
            }

            logger.info(
                f"  • Corrections réussies: {self.correction_stats['corrected']}\n"
                f"  • Corrections échouées: {self.correction_stats['failed']}\n"
                f"  • Erreurs en attente: {self.correction_stats['pending']}"
            )

            # =================================================================
            # RECONSTRUCTION EPUB
            # =================================================================
            logger.info("=" * 60)
            logger.info("🔨 RECONSTRUCTION EPUB")
            logger.info("=" * 60)

            logger.info("  • Reconstruction des pages HTML...")
            for item in html_items:
                reconstruct_html_item(item)
                target_book.add_item(item)

            # Sauvegarder EPUB traduit
            logger.info(f"  • Sauvegarde EPUB traduit: {output_epub}")
            if not output_epub.parent.exists():
                output_epub.parent.mkdir(parents=True, exist_ok=True)

            epub.write_epub(output_epub, target_book)

            # =================================================================
            # STATISTIQUES FINALES
            # =================================================================
            duration = time.time() - start_time

            stats = {
                "phase1": self.phase1_stats,
                "phase2": self.phase2_stats,
                "corrections": self.correction_stats,
                "glossary": glossary_stats,
                "total_duration": duration,
            }

            logger.info("=" * 60)
            logger.info("✅ PIPELINE TERMINÉ")
            logger.info("=" * 60)
            logger.info(
                f"📊 RÉSUMÉ:\n"
                f"  • Phase 1: {self.phase1_stats['translated']}/{self.phase1_stats['total_chunks']} chunks traduits\n"
                f"  • Phase 2: {self.phase2_stats['refined']}/{self.phase2_stats['total_chunks']} chunks affinés\n"
                f"  • Corrections: {self.correction_stats['corrected']} réussies, {self.correction_stats['failed']} échouées\n"
                f"  • Glossaire: {glossary_stats['total_terms']} termes, {glossary_stats['validated_terms']} validés\n"
                f"  • Durée totale: {duration:.1f}s\n"
                f"  • EPUB final: {output_epub}"
            )

            return stats

        except KeyboardInterrupt:
            logger.error("❌ Pipeline interrompu par l'utilisateur")
            if self.correction_worker:
                self.correction_worker.stop(timeout=5.0)
            raise

        except Exception as e:
            logger.exception(f"❌ Erreur fatale dans le pipeline: {e}")
            if self.correction_worker:
                self.correction_worker.stop(timeout=5.0)
            raise

    def get_failed_errors(self) -> list:
        """
        Récupère la liste des erreurs non récupérables.

        Returns:
            Liste des ErrorItem qui ont échoué après tous les retries

        Example:
            >>> failed = pipeline.get_failed_errors()
            >>> for error in failed:
            ...     print(f"Chunk {error.chunk.index}: {error.error_type}")
        """
        return self.error_queue.get_failed_items()

    def clear_caches(self) -> None:
        """
        Supprime tous les caches (initial, refined, glossaire).

        Attention: Opération irréversible.

        Example:
            >>> pipeline.clear_caches()
        """
        logger.warning("🗑️ Suppression de tous les caches...")
        self.multi_store.clear_all()
        glossary_path = self.cache_dir / "glossary.json"
        if glossary_path.exists():
            glossary_path.unlink()
        logger.info("✅ Caches supprimés")
