"""Phase 0 : Analyse littéraire stratifiée pour contexte de traduction.

Validation **entièrement schéma** : le modèle `AnalyseChapter` est passé au
LLM via Instructor (`JsonRequestConfig`), qui garantit la structure côté
API. Il n'y a donc pas de `content_checks` : le parsing JSON et le contrôle des
sections obligatoires sont absorbés par Pydantic.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, override

from ebook_translator.exporter import AnalysisExporter
from ebook_translator.llm.llm_config import JsonRequestConfig
from ebook_translator.logger import get_logger
from ebook_translator.persistence.memoized_chunk_persister import (
    MemoizedChunkPersister,
)
from ebook_translator.pipeline import ChunkContext, ExecutionMode, PhaseBase, PhaseName
from ebook_translator.segmentation.chapter_chunk import ChapterPartChunk
from template.phase.analyze_chapter_layered_models import AnalyseChapter
from template.types import ConvertibleModel

logger = get_logger(__name__)

_PERSISTER = MemoizedChunkPersister(AnalyseChapter)
"""Persister de la phase, isolé du champ `PhaseBase.persister`.

Ce dernier est déclaré `ChunkPersister[...] | None` (voie non migrée
possible) et ne donne donc pas accès à `all_for_outer`. La constante
garde le type concret pour la lecture des fiches voisines.
"""


@dataclass
class LiteraryAnalysisPhase(
    PhaseBase[ChapterPartChunk, AnalyseChapter, AnalyseChapter]
):
    """
    Phase 0 : analyse littéraire stratifiée pour contexte de traduction.

    Produit une fiche `AnalyseChapter` par bloc de chapitre :
    - `noyau_stable` : genre, registre, style, tonalité, pistes de traduction
    - `couche_narrative` : résumé, arcs, tensions, thèmes, références

    Chaque bloc reprend la fiche du bloc précédent (mode incrémental) et la
    met à jour. Les fiches sont mémoïsées par fingerprint de chunk, un
    fichier de cache par chapitre.
    """

    name = PhaseName.LITERARY_ANALYSIS
    chunk_type = ChapterPartChunk
    payload_type = AnalyseChapter
    data_type = AnalyseChapter

    max_tokens: int = field(  # Un seul bloc par chapitre (vs 4000 multi-blocs avant)
        default=5000
    )
    overlap_ratio: float = field(default=0.0, init=False)
    head_tail_balance: float = field(default=0, init=False)
    execution_mode = ExecutionMode.SEQUENTIAL

    max_workers: int = field(
        default=1, init=False
    )  # Analyse séquentielle pour cohérence

    # Validation portée par le schéma Pydantic seul (voir docstring module).
    content_checks = ()

    persister = _PERSISTER

    @override
    def get_chunks(self) -> Sequence[ChapterPartChunk]:
        """
        Retourne un chunk unique par chapitre pour analyse complète.

        Un chapitre plus long que `max_tokens` est découpé en plusieurs
        blocs, analysés en série : chacun reprend et enrichit la fiche du
        précédent (cf. `render_prompt`).
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

    def latest_analysis_for(self, chapter_name: str) -> AnalyseChapter | None:
        """Fiche consolidée d'un chapitre, pour les phases aval.

        Les fiches sont incrémentales : chaque bloc reprend et enrichit celle
        du bloc précédent. La **dernière écrite** consolide donc tout le
        chapitre — l'ordre d'itération suit l'ordre d'écriture des blocs.

        Injectée dans `Chapters` sous forme de callable (`analysis_lookup`) :
        `segmentation` n'a ainsi à connaître ni le `StoreManager`, ni le
        `ByteStore`, ni le persister de cette phase.

        Args:
            chapter_name: Nom du chapitre (clé de regroupement du cache).

        Returns:
            Dernière fiche mémoïsée du chapitre, ou `None` si la phase n'a
            pas tourné dessus.
        """
        entries = _PERSISTER.all_for_outer(chapter_name, self.get_byte_store())
        if not entries:
            return None
        return list(entries.values())[-1]

    def _snapshot_for(self, outer_key: str, global_index: int) -> str | None:
        """Fiche mémoïsée d'un bloc voisin, sérialisée en JSON.

        Args:
            outer_key: Chapitre où chercher (clé de regroupement du cache).
            global_index: Index global du bloc recherché (`chapitre * 100 + part`).

        Returns:
            JSON de la fiche si elle est en cache, `None` sinon.
        """
        entries = _PERSISTER.all_for_outer(outer_key, self.get_byte_store())
        prefix = f"{global_index}_"
        for inner_key, analyse in entries.items():
            if inner_key.startswith(prefix):
                return analyse.model_dump_json()
        return None

    def _previous_block_snapshot(self, chunk: ChapterPartChunk) -> str | None:
        """Fiche du bloc précédent **du même chapitre** (mode incrémental)."""
        if chunk.is_first():
            return None
        return self._snapshot_for(chunk.outer_key, chunk.index - 1)

    def _previous_chapter_snapshot(self, context: ChunkContext) -> str | None:
        """Fiche finale du chapitre précédent, amorce du chapitre courant (seed)."""
        previous = context.previous_chunk
        if not isinstance(previous, ChapterPartChunk):
            return None
        return self._snapshot_for(previous.outer_key, previous.index)

    @override
    def render_prompt(
        self, chunk: ChapterPartChunk, context: ChunkContext
    ) -> tuple[str, str]:
        """Génère le prompt d'analyse stratifiée.

        Trois modes, résolus par le renderer selon les snapshots fournis :
        incrémental (bloc N>0 du chapitre), seed (premier bloc, fiche du
        chapitre précédent en amorce), bootstrap (tout premier bloc du livre).
        """
        existing = self._previous_block_snapshot(chunk)
        seed = self._previous_chapter_snapshot(context) if existing is None else None
        return context.llm.renderer.render_analyze_chapter_layered(
            chunk=chunk,
            target_language=context.target_language,
            existing_analysis_json=existing,
            seed_analysis_json=seed,
            bootstrap=existing is None and seed is None,
        )

    @override
    def get_llm_config(
        self, chunk: ChapterPartChunk, context: ChunkContext
    ) -> JsonRequestConfig[ConvertibleModel[Any]]:
        """Voie Instructor : la structure est portée par le schéma Pydantic."""
        return JsonRequestConfig(config=self.llm, response_model=AnalyseChapter)

    @override
    def after_chunk(
        self,
        chunk: ChapterPartChunk,
        data: AnalyseChapter,
        context: ChunkContext,
    ) -> None:
        """Exporte la fiche en Markdown pour revue humaine."""
        AnalysisExporter.save_analysis_markdown(
            data, self.get_store().cache_dir / f"{chunk.outer_key}.md"
        )
