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

from ..checks import ValidationPipeline
from ..checks.fragment_count_check import FragmentCountCheck
from ..checks.line_count_check import LineCountCheck
from ..glossary import Glossary
from ..logger import get_logger
from ..segment import Segmentator
from ..stores.multi_store import MultiStore
from ..translation.epub_handler import (
    copy_epub_metadata,
    extract_html_items_in_spine_order,
    reconstruct_html_item,
)
from ..validation import ValidationWorkerPool
from ..validation.validation_worker_pool import ValidationPoolStats
from .glossary_validator import GlossaryValidator
from .phase1_worker import Phase1Worker
from .phase2_worker import Phase2Worker

if TYPE_CHECKING:
    from ..llm import LLM
    from ..segment import Chunk
    from ..translation.language import Language

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

    4. Validation asynchrone :
       - Thread pool dédié pour validation
       - Retry automatique via ValidationPipeline
       - Erreurs bloquantes (chunks rejetés si échec)

    5. Reconstruction EPUB :
       - Fallback refined → initial → original
       - Métadonnées préservées

    Attributes:
        llm: Instance LLM pour traduction et affinage
        epub_path: Chemin vers l'EPUB source
        cache_dir: Répertoire racine des caches
        multi_store: Gestionnaire initial_store + refined_store
        glossary: Glossary unifié pour cohérence
        validation_pool: Pool de workers pour validation asynchrone

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
        cache_dir: str | Path | None = None,
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
        match cache_dir:
            case None:
                cache_dir = Path(
                    self.epub_path.parent / f".{self.epub_path.stem}_cache"
                )
            case str():
                cache_dir = Path(cache_dir)
        self.cache_dir = cache_dir

        # Valider que l'EPUB existe
        if not self.epub_path.exists():
            raise FileNotFoundError(f"EPUB source introuvable : {self.epub_path}")

        # Créer cache_dir si nécessaire
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialiser infrastructure
        self.multi_store = MultiStore(self.cache_dir)
        self.glossary = Glossary(cache_path=self.cache_dir / "glossary.json")
        self.validation_pool: ValidationWorkerPool | None = None

        # Statistiques globales
        self.phase1_stats: dict = {}
        self.phase2_stats: dict = {}
        self.validation_stats: ValidationPoolStats = {
            "validated": 0,
            "rejected": 0,
            "pending": 0,
            "total_submitted": 0,
        }
        self.glossary_pairs_learned = 0

    def _learn_glossary_from_validated_chunk(
        self, chunk: "Chunk", final_translations: dict[int, str]
    ) -> None:
        """
        Callback appelé après validation réussie pour apprendre le glossaire.

        Cette méthode est passée comme callback au ValidationWorkerPool et
        est appelée uniquement après que les traductions ont été validées
        et corrigées par le pipeline.

        Args:
            chunk: Chunk avec textes originaux
            final_translations: Traductions finales validées {line_index: text}
        """
        try:
            # Parcourir les paires (original, traduit)
            for (page, tag_key, original_text), (idx, translated_text) in zip(
                chunk.fetch(), final_translations.items()
            ):
                if original_text and translated_text:
                    # Apprendre la paire (extraction automatique)
                    self.glossary.learn_pair(original_text, translated_text)
                    self.glossary_pairs_learned += 1

            logger.debug(
                f"📚 Glossaire appris depuis chunk {chunk.index} validé "
                f"({self.glossary_pairs_learned} paires au total)"
            )

        except Exception as e:
            logger.warning(
                f"⚠️ Erreur lors de l'apprentissage glossaire depuis chunk {chunk.index}: {e}"
            )
            # Non-bloquant : ne pas faire échouer la validation

    def run(
        self,
        target_language: "Language | str",
        output_epub: str | Path,
        phase1_workers: int = 4,
        phase1_max_tokens: int = 1500,
        phase2_max_tokens: int = 300,
        correction_workers: int = 2,
        validation_timeout: float = 30.0,
        auto_validate_glossary: bool = False,
    ) -> dict:
        """
        Exécute le pipeline complet de traduction en 2 phases.

        Args:
            target_language: Langue cible (enum Language ou str)
            output_epub: Chemin de sortie pour l'EPUB traduit
            phase1_workers: Nombre de threads parallèles Phase 1 (défaut: 4)
            phase1_max_tokens: Taille max chunks Phase 1 (défaut: 1500)
            phase2_max_tokens: Taille max chunks Phase 2 (défaut: 300)
            correction_workers: Nombre de threads parallèles pour corrections (défaut: 2)
            validation_timeout: Timeout pour arrêt ValidationWorkerPool (défaut: 30s)
            auto_validate_glossary: Si True, résout automatiquement les conflits
                                   sans demander validation utilisateur (défaut: False)

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
        from ..translation.language import Language

        target_language_str = (
            target_language.value
            if isinstance(target_language, Language)
            else target_language
        )

        output_epub = (
            output_epub if isinstance(output_epub, Path) else Path(output_epub)
        )

        logger.info(
            f"🚀 Démarrage pipeline 2 phases : {self.epub_path} → {output_epub}"
        )
        logger.info(f"  • Langue cible: {target_language_str}")
        logger.info(
            f"  • Phase 1: {phase1_max_tokens} tokens, {phase1_workers} workers"
        )
        logger.info(f"  • Phase 2: {phase2_max_tokens} tokens, séquentiel")
        logger.info(f"  • Corrections: {correction_workers} workers parallèles")

        # =====================================================================
        # CHARGEMENT EPUB
        # =====================================================================
        logger.info("📖 Chargement de l'EPUB source...")
        source_book = epub.read_epub(self.epub_path)
        html_items, target_book = extract_html_items_in_spine_order(source_book)
        copy_epub_metadata(source_book, target_book, str(target_language_str))
        logger.info(f"  • {len(html_items)} chapitres extraits")

        # =====================================================================
        # DÉMARRAGE VALIDATION WORKER POOL
        # =====================================================================
        logger.info("🔧 Démarrage du pool de validation...")
        pipeline = ValidationPipeline([
            LineCountCheck(),
            FragmentCountCheck(),
        ])
        self.validation_pool = ValidationWorkerPool(
            num_workers=correction_workers,  # Réutiliser paramètre (défaut: 2)
            pipeline=pipeline,
            store=self.multi_store.initial_store,  # Commence avec initial
            llm=self.llm,
            target_language=target_language_str,
            phase="initial",
            on_validated=self._learn_glossary_from_validated_chunk,  # Apprendre glossaire après validation
        )
        self.validation_pool.start()

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
            logger.info(
                f"  • {len(chunks_phase1)} chunks créés ({phase1_max_tokens} tokens)"
            )

            # Worker Phase 1
            phase1_worker = Phase1Worker(
                llm=self.llm,
                store=self.multi_store.initial_store,
                validation_pool=self.validation_pool,
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

            # 1. Attendre fin de la validation Phase 1
            logger.info("⏳ Attente de fin des validations Phase 1...")
            self.validation_pool.wait_completion()

            # Afficher statistiques de validation
            validation_stats = self.validation_pool.get_statistics()
            logger.info(
                f"✅ Validation Phase 1 terminée:\n"
                f"  • Validés: {validation_stats['validated']}\n"
                f"  • Rejetés: {validation_stats['rejected']}"
            )

            if validation_stats['rejected'] > 0:
                raise RuntimeError(
                    f"❌ {validation_stats['rejected']} chunk(s) rejeté(s) après validation Phase 1\n"
                    "Veuillez vérifier les logs pour plus de détails."
                )

            # 2. Validation du glossaire
            logger.info("\n📚 Validation du glossaire avant Phase 2...")
            validator = GlossaryValidator(self.glossary)

            glossary_validated = validator.validate_interactive(
                auto_resolve=auto_validate_glossary
            )

            if not glossary_validated:
                raise RuntimeError(
                    "❌ Validation du glossaire annulée par l'utilisateur.\n"
                    "La Phase 2 ne peut pas démarrer sans un glossaire validé."
                )

            logger.info(
                "✅ Glossaire validé"
                + (
                    " automatiquement"
                    if auto_validate_glossary
                    else " par l'utilisateur"
                )
            )

            # Switch store pour refined
            self.multi_store.switch_to_refined()
            logger.info("  • MultiStore basculé vers refined_store")

            # Recréer ValidationWorkerPool pour Phase 2 (refined_store)
            logger.info("🔄 Recréation ValidationWorkerPool pour Phase 2 (refined)...")
            self.validation_pool = ValidationWorkerPool(
                num_workers=correction_workers,
                pipeline=pipeline,  # Réutiliser même pipeline
                store=self.multi_store.refined_store,  # ← Changé pour refined
                llm=self.llm,
                target_language=target_language_str,
                phase="refined",  # ← Changé pour refined
            )
            self.validation_pool.start()
            logger.info("  • ValidationWorkerPool basculé vers refined_store")

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
            logger.info(
                f"  • {len(chunks_phase2)} chunks créés ({phase2_max_tokens} tokens)"
            )

            # Worker Phase 2
            phase2_worker = Phase2Worker(
                llm=self.llm,
                multi_store=self.multi_store,
                validation_pool=self.validation_pool,
                glossary=self.glossary,
                target_language=target_language_str,
            )

            # Exécuter Phase 2
            self.phase2_stats = phase2_worker.run_sequential(chunks=chunks_phase2)

            # =================================================================
            # FINALISATION VALIDATIONS
            # =================================================================
            logger.info("=" * 60)
            logger.info("🛑 FINALISATION DES VALIDATIONS")
            logger.info("=" * 60)

            # Arrêter ValidationWorkerPool proprement
            logger.info("  • Attente de fin des validations Phase 2...")
            self.validation_pool.wait_completion()

            # Statistiques validations finales
            self.validation_stats = self.validation_pool.get_statistics()

            logger.info(
                f"  • Validés (total): {self.validation_stats['validated']}\n"
                f"  • Rejetés (total): {self.validation_stats['rejected']}\n"
                f"  • En attente: {self.validation_stats['pending']}"
            )

            if self.validation_stats['rejected'] > 0:
                logger.warning(
                    f"⚠️ {self.validation_stats['rejected']} chunk(s) ont été rejetés "
                    f"(n'ont pas passé la validation après corrections)"
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
                "validation": self.validation_stats,
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
                f"  • Validation: {self.validation_stats['validated']} validés, {self.validation_stats['rejected']} rejetés\n"
                f"  • Glossaire: {glossary_stats['total_terms']} termes, {glossary_stats['validated_terms']} validés\n"
                f"  • Durée totale: {duration:.1f}s\n"
                f"  • EPUB final: {output_epub}"
            )

            return stats

        except KeyboardInterrupt:
            logger.error("❌ Pipeline interrompu par l'utilisateur")
            if self.validation_pool:
                self.validation_pool.wait_completion()
            raise

        except Exception as e:
            logger.exception(f"❌ Erreur fatale dans le pipeline: {e}")
            if self.validation_pool:
                self.validation_pool.wait_completion()
            raise

    def get_validation_stats(self) -> ValidationPoolStats:
        """
        Récupère les statistiques de validation.

        Returns:
            Dictionnaire avec statistiques de validation

        Example:
            >>> stats = pipeline.get_validation_stats()
            >>> print(f"Validés: {stats['validated']}, Rejetés: {stats['rejected']}")
        """
        if self.validation_pool:
            return self.validation_pool.get_statistics()
        return self.validation_stats

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
