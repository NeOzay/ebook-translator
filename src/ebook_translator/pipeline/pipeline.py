"""
Orchestrateur de pipeline modulaire.
"""

import time
from pathlib import Path
from typing import TYPE_CHECKING

from ebooklib import epub

from ebook_translator.glossary import Glossary
from ebook_translator.htmlpage import BilingualFormat, HtmlPage
from ebook_translator.logger import get_logger
from ebook_translator.pipeline.base import PhaseName, PhaseProtocol
from ebook_translator.pipeline.context import CommunContext, PhaseContext, PhaseStats
from ebook_translator.pipeline.executor import PhaseExecutor
from ebook_translator.pipeline.phases.dummy_phase import DummyPhase
from ebook_translator.pipeline.store_manager import StoreManager
from ebook_translator.segmentation import Chapters
from ebook_translator.segmentation.chapter import AnalysisLookup
from ebook_translator.translation.epub_handler import (
    copy_epub_metadata,
    extract_html_items_in_spine_order,
    reconstruct_html_item,
)
from ebook_translator.validation import ValidationWorkerPool

if TYPE_CHECKING:
    from ebook_translator.llm import LLM

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
        llm: LLM,
        epub_path: str | Path,
        phases: list[PhaseProtocol],
        cache_dir: str | Path | None = None,
        num_validation_workers: int = 2,
    ):
        """
        Initialise le pipeline.

        Args:
            llm: Instance LLM pour traduction
            epub_path: Chemin vers l'EPUB source
            cache_dir: Répertoire racine du cache
            phases: Liste des phases à exécuter (dans l'ordre)
            num_validation_workers: Nombre de workers pour validation (défaut: 2)
        """
        self.llm = llm
        self.epub_path = epub_path if isinstance(epub_path, Path) else Path(epub_path)
        # Valider que l'EPUB existe
        if not self.epub_path.exists():
            raise FileNotFoundError(f"EPUB source introuvable : {self.epub_path}")
        if cache_dir is None:
            self.cache_dir = self.epub_path.parent / f".{self.epub_path.stem}_cache"
        else:
            self.cache_dir = (
                cache_dir if isinstance(cache_dir, Path) else Path(cache_dir)
            )
        self.phases = phases
        self.num_validation_workers = num_validation_workers

        # Créer cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Valider dépendances entre phases
        self._validate_dependencies()

        # Infrastructure (créée au démarrage)
        self.store_manager: StoreManager | None = None
        self.validation_pool: ValidationWorkerPool | None = None
        self.glossary: Glossary | None = None

    def _validate_dependencies(self) -> None:
        """
        Vérifie que les dépendances entre phases sont satisfaites.

        Raises:
            ValueError: Si une dépendance n'est pas satisfaite
        """
        executed_phases: set[str] = set()

        for phase_class in self.phases:
            for dep_class in phase_class.get_dependencies():
                if dep_class.name not in executed_phases:
                    raise ValueError(
                        f"Phase '{phase_class.name}' depends on '{dep_class.name}', "
                        f"but '{dep_class.name}' is not executed before it.\n"
                        f"Current order: {[p.name for p in self.phases]}"
                    )
            executed_phases.add(phase_class.name)

        logger.info(f"✅ Phase dependencies validated: {list(executed_phases)}")

    def _glossary_export_path(self, glossary: Glossary) -> Path:
        """Chemin d'export du glossaire enrichi par le run.

        Le glossaire source (`Glossary.cache_path`, chargé au démarrage) est
        traité en lecture seule : il peut avoir été révisé à la main, et une
        réécriture par le pipeline écraserait ces corrections. Quand le nom
        d'export par défaut désigne ce même fichier, on bascule sur un nom
        dérivé plutôt que d'écraser.

        Args:
            glossary: Glossaire du run, dont `cache_path` porte la source.

        Returns:
            Chemin d'écriture, garanti distinct de la source.
        """
        export_path = self.epub_path.parent / f".{self.epub_path.stem}_glossary.json"

        source = glossary.cache_path
        if source is not None and source.resolve() == export_path.resolve():
            export_path = export_path.with_suffix(".generated.json")

        return export_path

    def _analysis_lookup(self) -> AnalysisLookup | None:
        """Accès aux fiches Phase 0, à injecter dans `Chapters`.

        Import local : `literary_analysis` importe `pipeline`, l'import au
        niveau module refermerait le cycle.

        Returns:
            `LiteraryAnalysisPhase.latest_analysis_for` si la phase est dans
            le pipeline, `None` sinon (les phases aval traduisent alors sans
            contexte littéraire).
        """
        from ebook_translator.pipeline.phases.literary_analysis import (
            LiteraryAnalysisPhase,
        )

        for phase in self.phases:
            if isinstance(phase, LiteraryAnalysisPhase):
                return phase.latest_analysis_for
        return None

    def run(
        self,
        target_language: str,
        output_epub: str | Path,
        glossary: Glossary | None = None,
        bilingual_format: BilingualFormat = BilingualFormat.SEPARATE_TAG,
    ) -> dict[PhaseName, PhaseStats]:
        """
        Exécute toutes les phases.

        Args:
            target_language: Langue cible (ex: "français", "english")
            output_epub: Chemin de sortie de l'EPUB traduit
            glossary: Glossaire optionnel (créé automatiquement si None)
            bilingual_format: Format de sortie bilingue (défaut: SEPARATE_TAG)

        Returns:
            Statistiques par phase (clé: nom de phase, valeur: PhaseStats)

        Raises:
            RuntimeError: Si une transition bloque ou si validation échoue
            KeyboardInterrupt: Si l'utilisateur interrompt
        """
        start_time = time.time()

        output_epub = (
            output_epub if isinstance(output_epub, Path) else Path(output_epub)
        )

        logger.info("=" * 70)
        logger.info("🚀 PIPELINE DE TRADUCTION MODULAIRE")
        logger.info("=" * 70)
        logger.info(f"  • EPUB source: {self.epub_path}")
        logger.info(f"  • EPUB cible: {output_epub}")
        logger.info(f"  • Langue cible: {target_language}")
        logger.info(f"  • Cache: {self.cache_dir}")
        logger.info(f"  • Phases: {[p.name for p in self.phases]}")

        try:
            # =================================================================
            # CHARGEMENT EPUB
            # =================================================================
            logger.info("\n📖 Chargement de l'EPUB source...")
            source_book = epub.read_epub(self.epub_path)  # type: ignore
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
            self.glossary = glossary or Glossary()

            logger.info(f"  • Glossaire Path: {self.glossary.cache_path or 'None'}")

            CommunContext(
                target_language=target_language,
                llm=self.llm,
                glossary=self.glossary,
                store_manager=self.store_manager,
                book=source_book,
                html_pages=html_items,
                chapters=Chapters(source_book, self._analysis_lookup()),
            )

            # ValidationWorkerPool (reconfiguré par chaque phase via switch_phase).
            self.validation_pool = ValidationWorkerPool(
                num_workers=self.num_validation_workers,
                phase=DummyPhase(),  # Sera switch par PhaseExecutor
            )
            self.validation_pool.start()
            logger.info(
                f"  • ValidationWorkerPool démarré ({self.num_validation_workers} workers)"
            )

            # =================================================================
            # EXÉCUTION DES PHASES
            # =================================================================
            stats: dict[PhaseName, PhaseStats] = {}

            for i, phase_object in enumerate(self.phases):
                logger.info("\n" + "=" * 70)
                logger.info(
                    f"📝 PHASE {i + 1}/{len(self.phases)}: {phase_object.name.upper()}"
                )
                logger.info("=" * 70)

                # -------------------------------------------------------------
                # Créer contexte de phase
                # -------------------------------------------------------------
                context = PhaseContext(
                    name=phase_object.name,
                    validation_pool=self.validation_pool,
                    previous_phases=stats.copy(),
                )

                phase_object.put_context(context)

                # -------------------------------------------------------------
                # Exécuter phase
                # -------------------------------------------------------------
                executor = PhaseExecutor(phase_object, context)
                phase_stats = executor.run()
                stats[phase_object.name] = phase_stats

            # =================================================================
            # FINALISATION
            # =================================================================
            logger.info("\n" + "=" * 70)
            logger.info("🛑 FINALISATION")
            logger.info("=" * 70)

            # Attendre la fin de toutes les validations
            logger.info("  • Arrêt du ValidationWorkerPool...")
            self.validation_pool.stop()

            # Sauvegarder glossaire
            if self.glossary:
                export_path = self._glossary_export_path(self.glossary)
                self.glossary.save(export_path)
                logger.info(f"  • Glossaire exporté: {export_path}")

            # =================================================================
            # RECONSTRUCTION EPUB
            # =================================================================
            logger.info("\n" + "=" * 70)
            logger.info("🔨 RECONSTRUCTION EPUB")
            logger.info("=" * 70)

            logger.info("  • Application des traductions aux pages HTML...")
            assert self.store_manager is not None

            for item in html_items:
                page = HtmlPage(item)  # Récupère l'instance Singleton existante
                source_file = str(item.file_name)

                # Fusionner les traductions de toutes les phases
                # (les phases suivantes écrasent les précédentes — plus raffinées)
                merged_translations: dict[str, str] = {}
                for phase in self.phases:
                    store = self.store_manager.get_store(phase.name)
                    merged_translations.update(store.get_from_file(source_file))

                # Appliquer les traductions disponibles
                for tag_key in list(page.to_translate.keys()):
                    translation = merged_translations.get(tag_key.index)
                    if translation:
                        page.replace_text(tag_key, translation, bilingual_format)

                # replace_text() appelle _save_content() automatiquement quand
                # to_translate est vide. Si des fragments restent (non-traduits /
                # rejetés), on force la sauvegarde partielle.
                if page.to_translate:
                    page.save()

            logger.info("  • Reconstruction des pages HTML...")
            for item in html_items:
                reconstruct_html_item(item)
                target_book.add_item(item)  # type: ignore

            # Sauvegarder EPUB traduit
            logger.info(f"  • Sauvegarde EPUB traduit: {output_epub}")
            if not output_epub.parent.exists():
                output_epub.parent.mkdir(parents=True, exist_ok=True)

            epub.write_epub(output_epub, target_book)  # type: ignore

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
                logger.info("\n📚 GLOSSAIRE:")
                logger.info(f"  • Termes: {glossary_stats['total_terms']}")
                logger.info(f"  • Validés: {glossary_stats['user_terms']}")

            logger.info(f"\n⏱️  DURÉE TOTALE: {duration:.1f}s")
            logger.info(f"📄 EPUB FINAL: {output_epub}")

            return stats

        except KeyboardInterrupt:
            logger.error("\n❌ Pipeline interrompu par l'utilisateur")
            if self.validation_pool:
                self.validation_pool.stop()
            raise

        except Exception as e:
            logger.exception(f"\n❌ Erreur fatale dans le pipeline: {e}")
            if self.validation_pool:
                self.validation_pool.stop()
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

        # Supprimer le glossaire exporté. Le glossaire source éventuellement
        # fourni au run n'est jamais touché : il n'appartient pas au cache.
        source = self.glossary.cache_path if self.glossary else None
        for glossary_path in (
            self.epub_path.parent / f".{self.epub_path.stem}_glossary.json",
            self.epub_path.parent / f".{self.epub_path.stem}_glossary.generated.json",
        ):
            if source is not None and source.resolve() == glossary_path.resolve():
                continue
            if glossary_path.exists():
                glossary_path.unlink()
                logger.info(f"  • Glossaire supprimé: {glossary_path}")

        logger.info("✅ Caches supprimés")
