"""Phase 0 : Analyse littéraire pour contexte de traduction."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, override

from template.types import LLMTermeGlossaire

from ebook_translator.checks import Check
from ebook_translator.checks.check_tests.validate_glossary import GlossaryChecks
from ebook_translator.exporter import GlossaryExporter
from ebook_translator.logger import get_logger
from ebook_translator.pipeline import ChunkContext, ExecutionMode, PhaseBase, PhaseName
from ebook_translator.segmentation.chunk import Chunk
from ebook_translator.validation.validation_queue import SaveItem
from ebook_translator.validator.glossary_validator import GlossaryValidator

if TYPE_CHECKING:
    from ebook_translator.llm.llm_config import LLMConfig

logger = get_logger(__name__)


@dataclass
class GlossaryPhase(PhaseBase):
    """
    Phase 0 : Analyse littéraire simplifiée pour contexte de traduction.

    Cette phase analyse chaque chapitre pour extraire :
    - Analyse littéraire (ton, style, thèmes, pistes de traduction)
    - Glossaire avec propositions de traduction

    Le format simplifié ContexteTraduction réduit de ~67% les tokens LLM
    par rapport à l'ancien ChapterAnalysis.
    """

    name = PhaseName.GLOSSARY
    chunk_type = Chunk
    max_tokens: int = field(  # Un seul bloc par chapitre (vs 4000 multi-blocs avant)
        default=2000
    )
    overlap_ratio: float = field(default=0.0, init=False)
    execution_mode = ExecutionMode.SEQUENTIAL

    max_workers: int = field(
        default=1, init=False
    )  # Analyse séquentielle pour cohérence

    checks: tuple[Check[Any], ...] = field(default=(GlossaryChecks(),), init=False)

    file_name: str = field(
        default="glossary", init=False
    )  # Nom de fichier pour stockage dans le store

    @override
    @classmethod
    def get_translation_cache(cls, chunk: Chunk) -> tuple[dict[int, str], bool]:
        """
        Récupère l'analyse JSON depuis le store si elle existe.

        Returns:
            Tuple (résultat, has_missing) où:
            - résultat: dict avec l'analyse (ou vide si pas trouvée)
            - has_missing: True si l'analyse est manquante, False sinon
        """
        store = cls.get_store()
        keyname = f"{chunk.index}_{chunk.calculate_chunk_hash()[:8]}"
        cached_json = store.get(cls.file_name, keyname)
        if cached_json is None:
            return ({}, True)  # Analyse manquante
        return ({0: cached_json}, False)  # Analyse trouvée

    @override
    def render_prompt(self, chunk: Chunk, context: ChunkContext) -> tuple[str, str]:
        """Génère le prompt d'analyse simplifiée."""
        return context.llm.renderer.render_glossary(
            chunk=chunk,
            target_language=context.target_language,
            glossary=context.glossary,
        )

    @override
    def get_llm_config(self, chunk: Chunk, context: ChunkContext) -> LLMConfig:
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

    def _populate_glossary(
        self, termes: list[LLMTermeGlossaire], chunk_index: int
    ) -> None:
        """
        Peuple le glossaire depuis l'analyse d'un chapitre.

        Extrait les termes depuis analysis["glossaire"] et les ajoute au glossaire
        en utilisant validate_translation() pour priorité maximale.

        Args:
            analysis: Contexte de traduction validé
            chapter_name: Nom du chapitre (pour logging)
        """
        terms_added = 0
        glossary = self.context.glossary

        for term_entry in termes:
            # Ajouter au glossaire (validate_translation)
            glossary.learn(term_entry)
            terms_added += 1

        logger.info(
            f"[GlossaryPhase] chunk {chunk_index} - {terms_added} termes ajoutés au glossaire (total: {len(glossary)})"
        )

    @override
    def save_item_builder(self, chunk: Chunk, final_result: dict[int, str]) -> SaveItem:
        """Construit l'item de sauvegarde pour le store."""
        result = final_result[0]  # ChapterChunk a toujours index 0
        keyname = f"{chunk.index}_{chunk.calculate_chunk_hash()[:8]}"
        store = self.get_store()

        def on_save(item: SaveItem) -> None:
            glossary = GlossaryValidator.load(item.final_result[0])
            # Peupler le glossaire global
            self._populate_glossary(glossary, chunk.index)
            # Exporter l'analyse en markdown pour revue humaine
            GlossaryExporter.save_glossary_markdown(
                glossary, store.cache_dir / f"chunk {chunk.index}.md"
            )

        return SaveItem(
            chunk=chunk,
            final_result=final_result,
            source_files={self.file_name: {keyname: result}},
            on_save=on_save,
        )
