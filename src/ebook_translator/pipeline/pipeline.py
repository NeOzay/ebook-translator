"""
Orchestrateur de pipeline modulaire.
"""

import time
from pathlib import Path
from typing import TYPE_CHECKING

from ebooklib import epub

from ebook_translator.logger import get_logger
from ebook_translator.pipeline.base import PhaseBase
from ebook_translator.pipeline.context import PhaseContext, PhaseStats
from ebook_translator.pipeline.store_manager import StoreManager
from ebook_translator.pipeline.executor import PhaseExecutor
from ebook_translator.transition.base import TransitionBase, TransitionContext
from ebook_translator.validation import ValidationWorkerPool
from ebook_translator.translation.epub_handler import (
    copy_epub_metadata,
    extract_html_items_in_spine_order,
    reconstruct_html_item,
)

if TYPE_CHECKING:
    from ebook_translator.llm import LLM
    from ebook_translator.glossary import Glossary

logger = get_logger(__name__)


class Pipeline:
    """
    Orchestre l'exécution de N phases avec transitions.

    Cette classe remplace TwoPhasePipeline avec une architecture modulaire
    permettant d'ajouter facilement de nouvelles phases.

    Exemple simple (2 phases):
        pipeline = Pipeline(
            llm=llm,
            epub_path="book.epub",
            cache_dir=Path("cache"),
            phases=[InitialTranslationPhase, RefinementPhase],
            transitions={
                ("initial", "refined"): GlossaryValidationTransition,
            },
        )

        stats = pipeline.run(
            target_language="français",
            output_epub=Path("book_fr.epub"),
        )

    Exemple avancé (3 phases):
        pipeline = Pipeline(
            llm=llm,
            epub_path="book.epub",
            cache_dir=Path("cache"),
            phases=[
                InitialTranslationPhase,
                RefinementPhase,
                QualityReviewPhase,  # Nouvelle phase!
            ],
            transitions={
                ("initial", "refined"): GlossaryValidationTransition,
                ("refined", "quality"): QualityThresholdTransition,
            },
        )
    """

    def __init__(
        self,
        llm: "LLM",
        epub_path: str | Path,
        cache_dir: str | Path,
        phases: list[type[PhaseBase]],
        transitions: dict[tuple[str, str], type[TransitionBase]] | None = None,
        num_validation_workers: int = 2,
    ):
        """
        Initialise le pipeline.

        Args:
            llm: Instance LLM pour traduction
            epub_path: Chemin vers l'EPUB source
            cache_dir: Répertoire racine du cache
            phases: Liste des classes de phases à exécuter (dans l'ordre)
            transitions: Transitions entre phases (optionnel)
                        Clé: (from_phase, to_phase)
                        Valeur: Classe TransitionBase
            num_validation_workers: Nombre de workers pour validation (défaut: 2)
        """
        self.llm = llm
        self.epub_path = epub_path if isinstance(epub_path, Path) else Path(epub_path)
        self.cache_dir = cache_dir if isinstance(cache_dir, Path) else Path(cache_dir)
        self.phases = phases
        self.transitions = transitions or {}
        self.num_validation_workers = num_validation_workers

        # Valider que l'EPUB existe
        if not self.epub_path.exists():
            raise FileNotFoundError(f"EPUB source introuvable : {self.epub_path}")

        # Créer cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Valider dépendances entre phases
        self._validate_dependencies()

        # Infrastructure (créée au démarrage)
        self.store_manager: StoreManager | None = None
        self.validation_pool: ValidationWorkerPool | None = None
        self.glossary: "Glossary | None" = None

    def _validate_dependencies(self) -> None:
        """
        Vérifie que les dépendances entre phases sont satisfaites.

        Raises:
            ValueError: Si une dépendance n'est pas satisfaite
        """
        executed_phases: set[str] = set()

        for phase_class in self.phases:
            for dep_class in phase_class.depends_on:
                if dep_class.name not in executed_phases:
                    raise ValueError(
                        f"Phase '{phase_class.name}' depends on '{dep_class.name}', "
                        f"but '{dep_class.name}' is not executed before it.\n"
                        f"Current order: {[p.name for p in self.phases]}"
                    )
            executed_phases.add(phase_class.name)

        logger.info(f"✅ Phase dependencies validated: {list(executed_phases)}")

    def _execute_transition(
        self,
        prev_phase_class: type[PhaseBase],
        phase_class: type[PhaseBase],
        stats: dict[str, PhaseStats],
    ) -> None:
        """
        Exécute la transition entre deux phases si définie.

        Args:
            prev_phase_class: Classe de la phase précédente
            phase_class: Classe de la phase actuelle
            stats: Statistiques des phases précédentes

        Raises:
            RuntimeError: Si la transition bloque (can_proceed retourne False)
        """
        transition_key = (prev_phase_class.name, phase_class.name)

        if transition_key not in self.transitions:
            return

        # Garantir que l'infrastructure est initialisée
        assert self.store_manager is not None, "StoreManager not initialized"
        assert self.validation_pool is not None, "ValidationWorkerPool not initialized"

        logger.info(f"\n🔄 Transition: {prev_phase_class.name} → {phase_class.name}")

        transition_class = self.transitions[transition_key]
        transition = transition_class()

        transition_context = TransitionContext(
            store_manager=self.store_manager,
            validation_pool=self.validation_pool,
            previous_stats=stats.copy(),
            glossary=self.glossary,
        )

        # Vérifier si la transition peut continuer
        can_proceed, msg = transition.can_proceed(transition_context)
        logger.info(f"  • {transition.name}: {msg}")

        if not can_proceed:
            raise RuntimeError(
                f"❌ Transition bloquée: {transition.name}\n"
                f"Raison: {msg}\n"
                f"La phase '{phase_class.name}' ne peut pas démarrer."
            )

        # Préparer la phase suivante
        transition.prepare_next_phase(transition_context)
        logger.info(f"  • Transition completed: {transition.name}")

    def run(
        self,
        target_language: str,
        output_epub: str | Path,
        glossary: "Glossary | None" = None,
        max_retries: int = 3,
    ) -> dict[str, PhaseStats]:
        """
        Exécute toutes les phases.

        Args:
            target_language: Langue cible (ex: "français", "english")
            output_epub: Chemin de sortie de l'EPUB traduit
            glossary: Glossaire optionnel (créé automatiquement si None)
            max_retries: Nombre max de retries pour les corrections (défaut: 3)

        Returns:
            Statistiques par phase (clé: nom de phase, valeur: PhaseStats)

        Raises:
            RuntimeError: Si une transition bloque ou si validation échoue
            KeyboardInterrupt: Si l'utilisateur interrompt
        """
        start_time = time.time()

        output_epub = output_epub if isinstance(output_epub, Path) else Path(output_epub)

        logger.info("=" * 70)
        logger.info("🚀 PIPELINE DE TRADUCTION MODULAIRE")
        logger.info("=" * 70)
        logger.info(f"  • EPUB source: {self.epub_path}")
        logger.info(f"  • EPUB cible: {output_epub}")
        logger.info(f"  • Langue cible: {target_language}")
        logger.info(f"  • Cache: {self.cache_dir}")
        logger.info(f"  • Phases: {[p.name for p in self.phases]}")
        logger.info(f"  • Transitions: {list(self.transitions.keys())}")

        try:
            # =================================================================
            # CHARGEMENT EPUB
            # =================================================================
            logger.info("\n📖 Chargement de l'EPUB source...")
            source_book = epub.read_epub(self.epub_path)
            html_items, target_book = extract_html_items_in_spine_order(source_book)
            copy_epub_metadata(source_book, target_book, target_language)
            logger.info(f"  • {len(html_items)} chapitres extraits")

            # =================================================================
            # INFRASTRUCTURE
            # =================================================================
            logger.info("\n🔧 Initialisation de l'infrastructure...")

            # Store manager
            self.store_manager = StoreManager(self.cache_dir, self.phases)
            logger.info(f"  • Stores créés: {self.store_manager.list_phases()}")

            # Glossaire
            if glossary is None:
                from ebook_translator.glossary import Glossary

                self.glossary = Glossary(cache_path=self.cache_dir / "glossary.json")
            else:
                self.glossary = glossary
            logger.info(f"  • Glossaire: {self.cache_dir / 'glossary.json'}")

            # ValidationWorkerPool (sera reconfiguré par chaque phase)
            # Créer un pipeline/store dummy pour initialisation (sera remplacé par PhaseExecutor)
            from ebook_translator.checks import ValidationPipeline
            dummy_pipeline = ValidationPipeline([])
            dummy_store = self.store_manager.get_store(self.phases[0].name)

            self.validation_pool = ValidationWorkerPool(
                num_workers=self.num_validation_workers,
                pipeline=dummy_pipeline,  # Sera switch par PhaseExecutor
                store=dummy_store,  # Sera switch par PhaseExecutor
                llm=self.llm,
                target_language=target_language,
                phase="initial",  # Sera switch par PhaseExecutor
                max_retries=max_retries,
            )
            self.validation_pool.start()
            logger.info(f"  • ValidationWorkerPool démarré ({self.num_validation_workers} workers)")

            # =================================================================
            # EXÉCUTION DES PHASES
            # =================================================================
            stats: dict[str, PhaseStats] = {}

            for i, phase_class in enumerate(self.phases):
                logger.info("\n" + "=" * 70)
                logger.info(f"📝 PHASE {i + 1}/{len(self.phases)}: {phase_class.name.upper()}")
                logger.info("=" * 70)

                # -------------------------------------------------------------
                # Exécuter transition (si définie)
                # -------------------------------------------------------------
                if i > 0:
                    prev_phase_class = self.phases[i - 1]
                    self._execute_transition(prev_phase_class, phase_class, stats)

                # -------------------------------------------------------------
                # Créer contexte de phase
                # -------------------------------------------------------------
                context = PhaseContext(
                    target_language=target_language,
                    html_items=html_items,
                    llm=self.llm,
                    store_manager=self.store_manager,
                    validation_pool=self.validation_pool,
                    glossary=self.glossary,
                    previous_phases=stats.copy(),
                )

                # -------------------------------------------------------------
                # Exécuter phase
                # -------------------------------------------------------------
                executor = PhaseExecutor(phase_class, context)
                phase_stats = executor.run()
                stats[phase_class.name] = phase_stats

            # =================================================================
            # FINALISATION
            # =================================================================
            logger.info("\n" + "=" * 70)
            logger.info("🛑 FINALISATION")
            logger.info("=" * 70)

            # Attendre la fin de toutes les validations
            logger.info("  • Arrêt du ValidationWorkerPool...")
            self.validation_pool.wait_completion()

            # Sauvegarder glossaire
            if self.glossary:
                self.glossary.save()
                logger.info(f"  • Glossaire sauvegardé: {self.cache_dir / 'glossary.json'}")

            # =================================================================
            # RECONSTRUCTION EPUB
            # =================================================================
            logger.info("\n" + "=" * 70)
            logger.info("🔨 RECONSTRUCTION EPUB")
            logger.info("=" * 70)

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

            logger.info("\n" + "=" * 70)
            logger.info("✅ PIPELINE TERMINÉ")
            logger.info("=" * 70)

            # Résumé par phase
            for phase_name, phase_stats in stats.items():
                logger.info(f"\n📊 {phase_name.upper()}:")
                logger.info(
                    f"  • Chunks: {phase_stats.chunks_processed}/{phase_stats.chunks_total}"
                )
                logger.info(f"  • Cache hits: {phase_stats.chunks_from_cache}")
                logger.info(f"  • Traduits: {phase_stats.chunks_translated}")
                logger.info(f"  • Validés: {phase_stats.chunks_validated}")
                logger.info(f"  • Rejetés: {phase_stats.chunks_rejected}")
                logger.info(f"  • Durée: {phase_stats.duration_seconds:.1f}s")

            # Glossaire
            if self.glossary:
                glossary_stats = self.glossary.get_statistics()
                logger.info(f"\n📚 GLOSSAIRE:")
                logger.info(f"  • Termes: {glossary_stats['total_terms']}")
                logger.info(f"  • Validés: {glossary_stats['validated_terms']}")

            logger.info(f"\n⏱️  DURÉE TOTALE: {duration:.1f}s")
            logger.info(f"📄 EPUB FINAL: {output_epub}")

            return stats

        except KeyboardInterrupt:
            logger.error("\n❌ Pipeline interrompu par l'utilisateur")
            if self.validation_pool:
                self.validation_pool.wait_completion()
            raise

        except Exception as e:
            logger.exception(f"\n❌ Erreur fatale dans le pipeline: {e}")
            if self.validation_pool:
                self.validation_pool.wait_completion()
            raise

    def clear_caches(self) -> None:
        """
        Supprime tous les caches de toutes les phases.

        Attention: Opération irréversible.
        """
        if self.store_manager is None:
            # Créer temporairement pour accéder aux stores
            self.store_manager = StoreManager(self.cache_dir, self.phases)

        logger.warning("🗑️  Suppression de tous les caches...")

        for phase_name in self.store_manager.list_phases():
            self.store_manager.clear_phase(phase_name)
            logger.info(f"  • Cache '{phase_name}' vidé")

        # Supprimer glossaire
        glossary_path = self.cache_dir / "glossary.json"
        if glossary_path.exists():
            glossary_path.unlink()
            logger.info("  • Glossaire supprimé")

        logger.info("✅ Caches supprimés")
