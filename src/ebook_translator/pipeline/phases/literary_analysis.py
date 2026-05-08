"""Phase 0 : Analyse littéraire pour contexte de traduction."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

from ebook_translator.checks import AnalysisChecks
from ebook_translator.exporter import AnalysisExporter
from ebook_translator.logger import get_logger
from ebook_translator.pipeline import ChunkContext, ExecutionMode, PhaseBase, PhaseName
from ebook_translator.segmentation.chapter_chunk import ChapterPartChunk
from ebook_translator.segmentation.chunk import Chunk
from ebook_translator.validation.validation_queue import SaveItem
from ebook_translator.validator import AnalysisValidator

if TYPE_CHECKING:
    from ebook_translator.llm.llm_config import CompleteLLMConfig

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
        default=5000
    )
    overlap_ratio: float = field(default=0.0, init=False)
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
        for chapter in self.context.chapters.iter_chapter_chunks():
            all_chunks.extend(
                chapter.split_chunk(
                    self.max_tokens,
                    self.overlap_ratio,
                    self.head_tail_balance,
                )
            )
        logger.info(
            f"Chapters detected: {len(all_chunks)} chunks "
            f"({[c.chapter.name for c in all_chunks]})"
        )
        return all_chunks

    @override
    def get_translation_cache(self, chunk: Chunk) -> tuple[dict[int, str], bool]:
        """
        Récupère l'analyse JSON depuis le store si elle existe.

        Returns:
            Tuple (résultat, has_missing) où:
            - résultat: dict avec l'analyse (ou vide si pas trouvée)
            - has_missing: True si l'analyse est manquante, False sinon
        """
        if not isinstance(chunk, ChapterPartChunk):
            raise TypeError(f"Expected ChapterPartChunk, got {type(chunk).__name__}")
        store = self.get_store()
        chapter_name = chunk.chapter.name
        keyname = f"{chunk.index}_{chunk.calculate_chunk_hash()[:8]}"
        cached_json = store.get(chapter_name, keyname)
        if cached_json is None:
            return ({}, True)  # Analyse manquante
        return ({0: cached_json}, False)  # Analyse trouvée

    def _get_previous_chunk_json(
        self, chunk: ChapterPartChunk, context: ChunkContext
    ) -> str | None:
        """Récupère le JSON d'analyse du chunk précédent depuis le store.

        Args:
            chunk: Chunk courant dont on veut le résultat du prédécesseur.

        Returns:
            JSON stringifié du chunk précédent, ou chaîne vide si introuvable.
        """
        if chunk.is_first():
            if not isinstance(context.previous_chunk, ChapterPartChunk):
                return None
            chapter_name = context.previous_chunk.chapter.name
            index = context.previous_chunk.total_parts
        else:
            chapter_name = chunk.chapter.name
            index = chunk.index

        all_cached = self.get_store().get_from_file(chapter_name)
        prefix = f"{index - 1}_"
        for key, value in all_cached.items():
            if key.startswith(prefix):
                analysis_data = AnalysisValidator.load(value)
                analysis_data = {
                    k: v
                    for k, v in analysis_data.items()
                    if k in ["chapitre", "analyse"]
                }
                return json.dumps(analysis_data, ensure_ascii=False, index=2)
        return None

    @override
    def render_prompt(self, chunk: Chunk, context: ChunkContext) -> tuple[str, str]:
        """Génère le prompt d'analyse simplifiée."""
        if not isinstance(chunk, ChapterPartChunk):
            raise ValueError("chunk must be ChapterPartChunk")

        return context.llm.renderer.render_analyze_chapter_layered(
            chunk=chunk,
            target_language=context.target_language,
            existing_analysis_json=self._get_previous_chunk_json(chunk),
        )

    @override
    def get_llm_config(self, chunk: Chunk, context: ChunkContext) -> CompleteLLMConfig:
        """Active le mode JSON pour parsing structuré."""
        conf = self.llm_config.copy()
        conf["use_json_mode"] = True
        return conf

    @override
    def process_llm_response(
        self, chunk: Chunk, response: str, context: ChunkContext
    ) -> dict[int, str]:
        """
        Valide la réponse JSON et peuple le glossaire.

        Args:
            chunk: ChapterPartChunk analysé
            response: JSON stringifié du LLM (ContexteTraduction)
            context: Contexte avec glossaire

        Returns:
            Dict {0: json_string} pour stockage dans le store

        Raises:
            ValueError: Si validation échoue ou JSON invalide
        """
        return {0: response}

    @override
    def save_item_builder(self, chunk: Chunk, final_result: dict[int, str]) -> SaveItem:
        """Construit l'item de sauvegarde pour le store."""
        if not isinstance(chunk, ChapterPartChunk):
            raise TypeError(f"Expected ChapterPartChunk, got {type(chunk).__name__}")
        result = final_result[0]  # ChapterChunk a toujours index 0
        store = self.get_store()
        name = chunk.chapter.name
        keyname = f"{chunk.index}_{chunk.calculate_chunk_hash()[:8]}"

        def on_save(item: SaveItem) -> None:
            analysis = AnalysisValidator.load(item.final_result[0])
            # Exporter l'analyse en markdown pour revue humaine
            AnalysisExporter.save_analysis_markdown(
                analysis, store.cache_dir / f"{name}.md", 0
            )

        return SaveItem(
            chunk=chunk,
            final_result=final_result,
            source_files={name: {keyname: result}},
            on_save=on_save,
        )
