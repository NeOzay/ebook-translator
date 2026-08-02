"""Phase glossaire : extraction des termes récurrents et de leur traduction.

Voie **texte** : le LLM répond en tableau délimité (`terme|type|sexe|
proposition`, terminé par `[=[END]=]`), que `LLMGlossaryModel` parse dans son
validateur `mode="before"`. Ce format coûte environ deux fois moins de tokens
de sortie que l'enveloppe JSON équivalente, et la sortie du glossaire est
volumineuse — une trentaine d'entrées par chunk.

Validation **entièrement schéma** : il n'y a pas de `content_checks`. Les
lignes malformées sont écartées au parsing plutôt que corrigées par un appel
supplémentaire, qui coûterait les tokens que ce format économise (voir
`template.phase.glossary_models`).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import override

from ebook_translator.exporter import GlossaryExporter
from ebook_translator.logger import get_logger
from ebook_translator.persistence.memoized_chunk_persister import (
    MemoizedChunkPersister,
)
from ebook_translator.pipeline import ChunkContext, ExecutionMode, PhaseBase, PhaseName
from ebook_translator.segmentation.chunk import Chunk
from ebook_translator.segmentation.segmentator import Segmentator
from template.phase.glossary_models import LLMGlossaryModel, LLMTermeGlossary

logger = get_logger(__name__)

_OUTER_KEY = "glossary"
"""Namespace de cache : un fichier unique pour tout le livre.

Contrairement à Phase 0 (un fichier par chapitre), les termes du glossaire
sont globaux — le découpage en chunks ne porte aucune sémantique de
regroupement.
"""

_PERSISTER = MemoizedChunkPersister(list[LLMTermeGlossary])


@dataclass
class GlossaryChunk(Chunk):
    """`Chunk` mémoïsable : expose les deux clés attendues par `MemoChunk`."""

    @classmethod
    def from_chunk(cls, chunk: Chunk) -> "GlossaryChunk":
        """Recopie un `Chunk` générique produit par le `Segmentator`.

        Args:
            chunk: Chunk source à convertir

        Returns:
            `GlossaryChunk` portant les mêmes fragments
        """
        return cls(
            index=chunk.index,
            head=chunk.head.copy(),
            body=chunk.body.copy(),
            tail=chunk.tail.copy(),
            token_count=chunk.token_count,
            token_encoding=chunk.token_encoding,
        )

    @property
    def outer_key(self) -> str:
        """Clé de regroupement `MemoChunk` : un seul fichier pour le livre."""
        return _OUTER_KEY

    @property
    def inner_key(self) -> str:
        """Fingerprint `MemoChunk` de ce chunk.

        Format identique à la clé utilisée par la voie `Store` legacy
        (`{index}_{hash[:8]}`) pour que les caches existants restent lisibles.
        """
        return f"{self.index}_{self.calculate_chunk_hash()[:8]}"


@dataclass
class GlossaryPhase(PhaseBase[GlossaryChunk, list[LLMTermeGlossary], LLMGlossaryModel]):
    """
    Phase glossaire : extraction des termes et de leur proposition de traduction.

    Chaque chunk produit une liste d'entrées, mémoïsée par fingerprint dans un
    fichier de cache unique. Les entrées alimentent le `Glossary` global, qui
    est ensuite réinjecté dans les prompts des phases de traduction.
    """

    name = PhaseName.GLOSSARY
    chunk_type = GlossaryChunk
    payload_type = LLMGlossaryModel
    data_type = list[LLMTermeGlossary]

    max_tokens: int = field(  # Un seul bloc par chapitre (vs 4000 multi-blocs avant)
        default=2000
    )
    overlap_ratio: float = field(
        default=0.5
    )  # 50% de chevauchement pour contexte complet
    head_tail_balance: float = field(default=0.5)
    execution_mode = ExecutionMode.SEQUENTIAL

    max_workers: int = field(
        default=1, init=False
    )  # Analyse séquentielle pour cohérence

    # Validation portée par le schéma Pydantic seul (voir docstring module).
    content_checks = ()

    persister = _PERSISTER

    @override
    def get_chunks(self) -> Sequence[GlossaryChunk]:
        """Segmente le livre entier, puis convertit en chunks mémoïsables."""
        segments = Segmentator(
            epub_source=self.context.html_pages,
            max_tokens=self.max_tokens,
            overlap_ratio=self.overlap_ratio,
            head_tail_balance=self.head_tail_balance,
        ).get_all_segments()
        return [GlossaryChunk.from_chunk(chunk) for chunk in segments]

    @override
    def render_prompt(
        self, chunk: GlossaryChunk, context: ChunkContext
    ) -> tuple[str, str]:
        """Génère le prompt d'extraction du glossaire."""
        return context.llm.renderer.render_glossary(
            chunk=chunk,
            target_language=context.target_language,
            glossary=context.glossary,
        )

    @override
    def on_save(
        self,
        chunk: GlossaryChunk,
        data: list[LLMTermeGlossary],
    ) -> None:
        """Peuple le glossaire global et exporte le Markdown de revue."""
        self._populate_glossary(data, chunk.index)
        GlossaryExporter.save_glossary_markdown(
            data, self.get_store().cache_dir / f"chunk {chunk.index}.md"
        )

    def _populate_glossary(
        self, termes: list[LLMTermeGlossary], chunk_index: int
    ) -> None:
        """
        Peuple le glossaire depuis les termes extraits d'un chunk.

        Args:
            termes: Entrées proposées par le LLM pour ce chunk
            chunk_index: Index du chunk (pour logging)
        """
        glossary = self.context.glossary

        for term_entry in termes:
            glossary.learn(term_entry)

        logger.info(
            f"[GlossaryPhase] chunk {chunk_index} - {len(termes)} termes ajoutés "
            f"au glossaire (total: {len(glossary)})"
        )
