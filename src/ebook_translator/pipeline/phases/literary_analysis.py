"""Phase 0 : Analyse littéraire pour contexte de traduction."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

from ebook_translator.analysis import AnalysisExporter, ContexteTraduction
from ebook_translator.analysis.validator import AnalysisValidator
from ebook_translator.checks import AnalysisChecks
from ebook_translator.logger import get_logger
from ebook_translator.pipeline import ChunkContext, ExecutionMode, PhaseBase, PhaseName
from ebook_translator.segmentation.chapter_chunk import ChapterChunk, ChapterPartChunk
from ebook_translator.segmentation.segmentator import Segmentator
from ebook_translator.validation.validation_queue import SaveItem

if TYPE_CHECKING:
    from ebook_translator.llm.llm_config import LLMConfig

logger = get_logger(__name__)


@dataclass
class LiteraryAnalysisPhase(PhaseBase[ChapterPartChunk]):
    """
    Phase 0 : Analyse littéraire simplifiée pour contexte de traduction.

    Cette phase analyse chaque chapitre pour extraire :
    - Analyse littéraire (ton, style, thèmes, pistes de traduction)
    - Glossaire avec propositions de traduction

    Le format simplifié ContexteTraduction réduit de ~67% les tokens LLM
    par rapport à l'ancien ChapterAnalysis.
    """

    name = PhaseName.LITERARY_ANALYSIS
    chunk_type = ChapterPartChunk
    max_tokens: int = field(  # Un seul bloc par chapitre (vs 4000 multi-blocs avant)
        default=70000
    )
    overlap_ratio: float = field(default=0.0)
    execution_mode = ExecutionMode.SEQUENTIAL

    max_workers: int = field(
        default=1, init=False
    )  # Analyse séquentielle pour cohérence

    checks = (AnalysisChecks(),)

    @override
    def get_chunks(self) -> Sequence[ChapterPartChunk]:
        """
        Retourne un chunk unique par chapitre pour analyse complète.

        Note: Le nouveau template simplifié traite le chapitre complet en un seul
        appel LLM (vs approche incrémentale multi-blocs de l'ancien système).
        """
        all_chunks: list[ChapterPartChunk] = []
        for chapter in Segmentator(
            self.context.html_items, self.max_tokens, self.overlap_ratio
        ).get_all_chapters_by_spine():
            all_chunks.extend(chapter.split_chunk(self.max_tokens, self.overlap_ratio))
        return all_chunks

    @override
    def get_translation_cache(
        self, chunk: ChapterPartChunk
    ) -> tuple[dict[int, str], bool]:
        """
        Récupère l'analyse JSON depuis le store si elle existe.

        Returns:
            Tuple (résultat, has_missing) où:
            - résultat: dict avec l'analyse (ou vide si pas trouvée)
            - has_missing: True si l'analyse est manquante, False sinon
        """
        store = self.context.store_manager.get_store(self.store_key())
        chapter_name = chunk.chapter.name
        keyname = f"{chunk.index}_{chunk.calculate_chunk_hash()[:8]}"
        cached_json = store.get(chapter_name, keyname)
        if cached_json is None:
            return ({}, True)  # Analyse manquante
        return ({0: cached_json}, False)  # Analyse trouvée

    @override
    def render_prompt(self, chunk: ChapterPartChunk, context: ChunkContext) -> str:
        """Génère le prompt d'analyse simplifiée."""
        if not isinstance(chunk, ChapterChunk):
            raise ValueError("chunk must be ChapterChunk")

        return context.llm.renderer.render_analyze_simplified(
            chapter_name=chunk.name,
            target_language=context.target_language,
        )

    @override
    def source_content(self, chunk: ChapterPartChunk, context: ChunkContext) -> str:
        """Retourne le contenu du chunk pour analyse."""
        return chunk.mark_lines_to_numbered([])

    @override
    def llm_config(self, chunk: ChapterPartChunk, context: ChunkContext) -> LLMConfig:
        """Active le mode JSON pour parsing structuré."""
        return {"use_json_mode": True}

    @override
    def process_llm_response(
        self, chunk: ChapterPartChunk, response: str, context: ChunkContext
    ) -> dict[int, str]:
        """
        Valide la réponse JSON et peuple le glossaire.

        Args:
            chunk: ChapterChunk analysé
            response: JSON stringifié du LLM (ContexteTraduction)
            context: Contexte avec glossaire

        Returns:
            Dict {0: json_string} pour stockage dans le store

        Raises:
            ValueError: Si validation échoue ou JSON invalide
        """
        return {0: response}

    def _populate_glossary(
        self,
        analysis: ContexteTraduction,
        chapter_name: str,
    ) -> None:
        """
        Peuple le glossaire depuis l'analyse d'un chapitre.

        Extrait les termes depuis analysis["glossaire"] et les ajoute au glossaire
        en utilisant validate_translation() pour priorité maximale.

        Args:
            analysis: Contexte de traduction validé
            glossary: Glossaire à peupler
            chapter_name: Nom du chapitre (pour logging)
        """
        terms_added = 0
        glossary = self.context.glossary

        for term_entry in analysis["glossaire"]:
            terme_original = term_entry["terme"].strip()
            proposition = term_entry["proposition_traduction"].strip()

            if not terme_original or not proposition:
                logger.warning(
                    f"[{chapter_name}] Skipping empty term or translation: "
                    f"'{terme_original}' -> '{proposition}'"
                )
                continue

            # Ajouter au glossaire avec priorité maximale (validate_translation)
            glossary.learn(terme_original, proposition)
            terms_added += 1

        logger.info(
            f"[{chapter_name}] Added {terms_added} terms to glossary from analysis"
        )

    @override
    def save_item_builder(
        self, chunk: ChapterPartChunk, final_result: dict[int, str]
    ) -> SaveItem:
        """Construit l'item de sauvegarde pour le store."""
        result = final_result[0]  # ChapterChunk a toujours index 0
        store = self.context.store_manager.get_store(self.store_key())
        name = chunk.chapter.name
        keyname = f"{chunk.index}_{chunk.calculate_chunk_hash()[:8]}"

        def on_save(item: SaveItem) -> None:
            analysis = AnalysisValidator.load(item.final_result[0])
            # Peupler le glossaire global
            self._populate_glossary(
                analysis,
                chapter_name=chunk.chapter.name,
            )
            # Exporter l'analyse en markdown pour revue humaine
            AnalysisExporter.export(analysis, store.cache_dir / f"{name}.md", 0)

        return SaveItem(
            chunk=chunk,
            final_result=final_result,
            source_files={name: {keyname: result}},
            on_save=on_save,
        )
