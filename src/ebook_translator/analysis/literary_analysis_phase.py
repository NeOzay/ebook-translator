"""
Phase 0: Analyse littéraire pré-traduction.

Cette phase analyse le contenu littéraire d'un EPUB chapitre par chapitre
avant la traduction. Elle génère des fiches d'analyse JSON contenant :
- Personnages et relations
- Lieux et atmosphère
- Éléments narratifs (conflits, révélations, foreshadowing)
- Thèmes et symboles
- Style et tonalité
- Terminologie spécialisée
- Considérations pour la traduction

Architecture:
    EPUB → Chapitres (spine) → AnalysisBlocks (4000 tokens) → JSON Analysis

Flux:
    1. Détection chapitres (ChapterDetector)
    2. Segmentation chunks (Segmentator)
    3. Re-segmentation blocs d'analyse (BlockSplitter)
    4. Analyse incrémentale (LLM JSON mode)
    5. Export JSON + Markdown
    6. Population glossaire automatique
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ..segmentation import Segmentator, Chunk
from ..segmentation.chapter_detector import ChapterDetector, ChapterDetectorConfig
from .block_splitter import BlockSplitter, AnalysisBlock
from .schema import ChapterAnalysis
from .validator import AnalysisValidator
from .analysis_exporter import AnalysisExporter

if TYPE_CHECKING:
    from ..llm import LLM
    from ebooklib import epub


logger = logging.getLogger(__name__)


class LiteraryAnalysisPhase:
    """
    Phase 0 : Analyse littéraire pré-traduction.

    Cette classe orchestre l'analyse littéraire d'un EPUB chapitre par chapitre.
    Elle utilise un LLM en mode JSON pour produire des fiches d'analyse structurées.

    Contrairement aux phases de traduction (Phase 1, 2), cette phase :
    - Ne traduit pas (pas de ValidationWorkerPool)
    - Travaille sur des blocs de 4000 tokens (vs 2000 pour traduction)
    - Produit des fichiers JSON/Markdown (vs traductions dans Store)
    - Utilise l'analyse incrémentale (enrichissement progressif)

    Args:
        llm: Instance LLM pour les requêtes d'analyse
        html_items: Liste des items HTML de l'EPUB à analyser
        output_dir: Répertoire de sortie pour les analyses (défaut: "cache/analysis")
        block_tokens: Nombre de tokens par bloc d'analyse (défaut: 4000)
        genre: Genre littéraire du livre (défaut: "fiction")

    Example:
        >>> from ebook_translator.llm import LLM
        >>> llm = LLM(model_name="deepseek-chat")
        >>> phase = LiteraryAnalysisPhase(
        ...     llm=llm,
        ...     html_items=epub.items,
        ...     output_dir="cache/analysis",
        ...     block_tokens=4000,
        ...     genre="science-fiction"
        ... )
        >>> analyses = phase.run()
        >>> print(f"Analyzed {len(analyses)} chapters")
    """

    def __init__(
        self,
        llm: "LLM",
        html_items: list["epub.EpubHtml"],
        output_dir: str | Path = "cache/analysis",
        block_tokens: int = 4000,
        genre: str = "fiction",
    ):
        """
        Initialise la phase d'analyse littéraire.

        Args:
            llm: Instance LLM pour les requêtes d'analyse
            html_items: Liste des items HTML de l'EPUB à analyser
            output_dir: Répertoire de sortie pour les analyses
            block_tokens: Nombre de tokens par bloc d'analyse (défaut: 4000)
            genre: Genre littéraire du livre (défaut: "fiction")
        """
        self.llm = llm
        self.html_items = html_items
        self.output_dir = Path(output_dir)
        self.block_tokens = block_tokens
        self.genre = genre

        # Créer le répertoire de sortie
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Composants
        self.segmentator = Segmentator(html_items)
        self.block_splitter = BlockSplitter(target_tokens=block_tokens)
        self.validator = AnalysisValidator()
        self.exporter = AnalysisExporter()

        logger.info(
            f"LiteraryAnalysisPhase initialisée: "
            f"output_dir={self.output_dir}, "
            f"block_tokens={block_tokens}, "
            f"genre={genre}"
        )

    def detect_chapters(self) -> dict[str, list[Chunk]]:
        """
        Détecte les chapitres via l'analyse de la spine EPUB.

        Utilise ChapterDetector pour grouper les fichiers HTML en chapitres
        logiques (gère multi-fichiers, inserts, prologue/epilogue).

        Returns:
            Dictionnaire {chapter_name: [chunks]}

        Raises:
            ValueError: Si aucun chapitre n'est détecté
        """
        logger.info("Détection des chapitres via spine EPUB...")

        # Créer le détecteur
        detector_config = ChapterDetectorConfig(use_llm_fallback=True)
        detector = ChapterDetector(
            html_items=self.html_items,
            llm=self.llm,
            config=detector_config,
        )

        # Grouper les chunks par chapitre
        chapters: dict[str, list[Chunk]] = {}
        for chunk in self.segmentator.get_all_chapters_by_spine(
            llm=self.llm, config=detector_config
        ):
            chapter_name = chunk.chapter_name or f"Chapter {chunk.index + 1}"

            if chapter_name not in chapters:
                chapters[chapter_name] = []

            chapters[chapter_name].append(chunk)

        if not chapters:
            raise ValueError("Aucun chapitre détecté dans l'EPUB")

        logger.info(f"Détecté {len(chapters)} chapitres: {list(chapters.keys())}")
        return chapters

    def split_into_blocks(
        self, chapters: dict[str, list[Chunk]]
    ) -> dict[str, list[AnalysisBlock]]:
        """
        Découpe les chapitres en blocs d'analyse de ~4000 tokens.

        Regroupe les chunks (2000 tokens) en blocs plus larges adaptés
        à l'analyse littéraire (compréhension narrative globale).

        Args:
            chapters: Dictionnaire {chapter_name: [chunks]}

        Returns:
            Dictionnaire {chapter_name: [AnalysisBlocks]}
        """
        logger.info("Découpage des chapitres en blocs d'analyse...")

        analysis_blocks = self.block_splitter.split_all_chapters(chapters)

        total_blocks = sum(len(blocks) for blocks in analysis_blocks.values())
        logger.info(f"Créé {total_blocks} blocs d'analyse au total")

        return analysis_blocks

    def analyze_chapter(
        self, chapter_name: str, blocks: list[AnalysisBlock]
    ) -> ChapterAnalysis:
        """
        Analyse un chapitre en utilisant l'approche incrémentale.

        Stratégie:
        1. Premier bloc: Initialise l'analyse (render_analyze_initial)
        2. Blocs suivants: Enrichit l'analyse (render_analyze_incremental)
        3. Dernier bloc: Finalise avec status="complete"

        Args:
            chapter_name: Nom du chapitre à analyser
            blocks: Liste des AnalysisBlocks constituant ce chapitre

        Returns:
            ChapterAnalysis complète et validée

        Raises:
            ValueError: Si l'analyse est invalide après toutes les tentatives
        """
        logger.info(f"Analyse de '{chapter_name}' ({len(blocks)} blocs)...")

        analysis_json: str | None = None

        for block in blocks:
            if block.is_first_block:
                # Premier bloc: Initialiser l'analyse
                logger.debug(
                    f"  Bloc {block.block_number}/{block.total_blocks}: "
                    f"Initialisation ({block.token_count} tokens)"
                )

                prompt = self.llm.renderer.render_analyze_initial(
                    chapter_name=chapter_name,
                    total_blocks=block.total_blocks,
                    block_text=block.text,
                    genre=self.genre,
                )

                analysis_json = self.llm.query(
                    system_prompt=prompt,
                    content="",
                    use_json_mode=True,
                )
            else:
                # Blocs suivants: Enrichir l'analyse
                logger.debug(
                    f"  Bloc {block.block_number}/{block.total_blocks}: "
                    f"Enrichissement ({block.token_count} tokens)"
                )

                if analysis_json is None:
                    raise ValueError(
                        f"Chapter '{chapter_name}', Block {block.block_number}: "
                        f"Analyse précédente manquante (incohérence interne)"
                    )

                prompt = self.llm.renderer.render_analyze_incremental(
                    chapter_name=chapter_name,
                    current_block=block.block_number,
                    total_blocks=block.total_blocks,
                    partial_analysis_json=analysis_json,
                    block_text=block.text,
                    is_last_block=block.is_last_block,
                    genre=self.genre,
                )

                analysis_json = self.llm.query(
                    system_prompt=prompt,
                    content="",
                    use_json_mode=True,
                )

        # Valider l'analyse finale
        if analysis_json is None:
            raise ValueError(f"Chapter '{chapter_name}': Aucune analyse générée")

        try:
            analysis_dict: ChapterAnalysis = json.loads(analysis_json)
        except json.JSONDecodeError as e:
            logger.error(f"Chapter '{chapter_name}': JSON invalide: {e}")
            raise ValueError(f"Chapter '{chapter_name}': JSON invalide: {e}")

        # Vérifier complétude
        errors = self.validator.validate(analysis_dict)
        if errors:
            logger.warning(
                f"Chapter '{chapter_name}': Analyse invalide:\n"
                + "\n".join(f"  - {err}" for err in errors)
            )
            # Ne pas bloquer, mais logger l'erreur

        if not self.validator.is_complete(analysis_dict):
            logger.warning(f"Chapter '{chapter_name}': Analyse incomplète (status != 'complete')")

        logger.info(
            f"Analyse de '{chapter_name}' terminée "
            f"({analysis_dict['blocks_analyzed']}/{analysis_dict['total_blocks']} blocs)"
        )

        return analysis_dict

    def save_analysis(self, chapter_name: str, analysis: ChapterAnalysis) -> tuple[Path, Path]:
        """
        Sauvegarde l'analyse au format JSON et Markdown.

        Génère deux fichiers:
        - {output_dir}/{chapter_name}.json : Analyse brute (pour parsing)
        - {output_dir}/{chapter_name}.md : Analyse formatée (pour lecture humaine)

        Args:
            chapter_name: Nom du chapitre
            analysis: Analyse à sauvegarder

        Returns:
            Tuple (chemin_json, chemin_md)
        """
        # Nettoyer le nom de fichier
        safe_name = chapter_name.replace("/", "_").replace("\\", "_").replace(":", "_")

        # Sauvegarder JSON
        json_path = self.output_dir / f"{safe_name}.json"
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)

        logger.info(f"Sauvegardé JSON: {json_path}")

        # Sauvegarder Markdown avec AnalysisExporter
        md_path = self.output_dir / f"{safe_name}.md"
        markdown_content = self.exporter.export_to_markdown(analysis)
        self.exporter.save_markdown(markdown_content, md_path)

        logger.info(f"Sauvegardé Markdown: {md_path}")

        return json_path, md_path

    def run(self) -> dict[str, ChapterAnalysis]:
        """
        Exécute la phase d'analyse littéraire complète.

        Flux:
        1. Détection chapitres (spine-based)
        2. Découpage en blocs d'analyse (4000 tokens)
        3. Analyse incrémentale chapitre par chapitre
        4. Sauvegarde JSON + Markdown
        5. Retourne les analyses

        Returns:
            Dictionnaire {chapter_name: ChapterAnalysis}

        Example:
            >>> phase = LiteraryAnalysisPhase(llm, html_items)
            >>> analyses = phase.run()
            >>> for chapter, analysis in analyses.items():
            ...     print(f"{chapter}: {len(analysis['characters']['present'])} personnages")
        """
        logger.info("=" * 80)
        logger.info("Phase 0: Analyse littéraire pré-traduction")
        logger.info("=" * 80)

        # 1. Détection chapitres
        chapters = self.detect_chapters()

        # 2. Découpage en blocs
        analysis_blocks = self.split_into_blocks(chapters)

        # 3. Analyse chapitre par chapitre
        results: dict[str, ChapterAnalysis] = {}

        for chapter_name, blocks in analysis_blocks.items():
            try:
                analysis = self.analyze_chapter(chapter_name, blocks)
                results[chapter_name] = analysis

                # 4. Sauvegarde
                self.save_analysis(chapter_name, analysis)

            except Exception as e:
                logger.error(f"Erreur lors de l'analyse de '{chapter_name}': {e}", exc_info=True)
                # Continuer avec les autres chapitres

        logger.info("=" * 80)
        logger.info(f"Phase 0 terminée: {len(results)}/{len(chapters)} chapitres analysés")
        logger.info("=" * 80)

        return results
