"""
Phase 2: Raffinage avec glossaire et petits blocs.
"""

from dataclasses import dataclass, field
from typing import override

from ebook_translator.checks import (
    FragmentCountCheck,
    LineCountCheck,
    PunctuationCheck,
    SentenceCheck,
)
from ebook_translator.checks.content import (
    FragmentCountCheck as ContentFragmentCountCheck,
)
from ebook_translator.checks.content import (
    LineCountCheck as ContentLineCountCheck,
)
from ebook_translator.checks.content import (
    PunctuationCheck as ContentPunctuationCheck,
)
from ebook_translator.checks.content import (
    SentenceCheck as ContentSentenceCheck,
)
from ebook_translator.logger import get_logger
from ebook_translator.persistence.line_indexed_persister import LineIndexedPersister
from ebook_translator.pipeline.base import ExecutionMode, PhaseBase, PhaseName
from ebook_translator.pipeline.context import ChunkContext
from ebook_translator.pipeline.phases.initial_translation import InitialTranslationPhase
from ebook_translator.segmentation.segmentator import Chunk
from ebook_translator.stores.byte_store import ByteStore, FileByteStore
from template.phase.translation_models import LineIndexedLLMResponse

logger = get_logger(__name__)


@dataclass
class RefinementPhase(PhaseBase[Chunk, dict[int, str]]):
    """
    Phase 2: Raffinage avec glossaire (petits blocs, séquentiel).

    Configuration:
    - max_tokens: 300 (petits blocs pour contrôle fin)
    - overlap_ratio: 1.0 (100% = chaque chunk inclut le précédent en entier)
    - execution_mode: SEQUENTIAL (séquentiel pour cohérence)
    - template: translate_refine (avec glossaire + traduction initiale)

    Validation:
    - LineCountCheck: Toutes les lignes traduites
    - FragmentCountCheck: Nombre correct de séparateurs </>
    - PunctuationCheck: Paires de guillemets correctes

    Note: SentenceCheck est retiré (déjà validé en Phase 1)

    Cette phase dépend de InitialTranslationPhase.
    """

    name = PhaseName.REFINEMENT
    chunk_type = Chunk
    max_tokens: int = field(default=300)
    overlap_ratio: float = field(default=1.0)  # 100% overlap pour contexte complet
    execution_mode = ExecutionMode.SEQUENTIAL
    max_workers: int = field(default=1, init=False)
    depends_on = (InitialTranslationPhase,)  # Nécessite Phase 1

    checks = (
        LineCountCheck(),
        FragmentCountCheck(),
        PunctuationCheck(),
        SentenceCheck(),
    )

    # Nouvelle API (étape 5+). Cohabite avec `checks` legacy ; le worker
    # unifié de l'étape 7 lira `payload_type` + `content_checks`.
    payload_type = LineIndexedLLMResponse
    content_checks = (
        ContentLineCountCheck(),
        ContentFragmentCountCheck(),
        ContentPunctuationCheck(),
        ContentSentenceCheck(),
    )

    persister = LineIndexedPersister(LineIndexedLLMResponse)

    @override
    def get_byte_fallback_store(self) -> ByteStore | None:
        """`FileByteStore` de Phase 1 — fallback du `LineIndexedPersister`.

        Le persister consulte ce store pour les indices absents du store
        principal de Phase 2 (chaîne de cache inter-phases).
        """

        cached = getattr(self, "_byte_fallback_store", None)
        if cached is not None:
            return cached
        initial_store = self.context.store_manager.get_store(PhaseName.INITIAL)
        store = FileByteStore(initial_store.cache_dir / self.BYTE_STORE_SUBDIR)
        self._byte_fallback_store = store
        return store

    @override
    def before_phase(self) -> None:  # noqa: B027
        store = self.get_store()
        initial_translation = self.context.store_manager.get_store(PhaseName.INITIAL)
        store.set_fallback(initial_translation)

    @override
    def render_prompt(self, chunk: Chunk, context: ChunkContext) -> tuple[str, str]:
        """
        Génère le prompt de raffinage.

        Utilise le template translate_refine avec:
        - Glossaire appris en Phase 1
        - Traduction initiale comme base
        - Analyse littéraire du chapitre (si Phase 0 exécutée)

        Args:
            chunk: Chunk à raffiner
            context: Contexte du chunk

        Returns:
            Prompt formaté pour le LLM
        """
        # Récupérer traduction initiale
        initial_translation = context.store_manager.get_store("initial")

        # Récupérer analyse littéraire si disponible
        literary_context = self.context.chapters.get_literary_analysis(chunk)

        # Rendre le prompt avec glossaire + traduction initiale + analyse littéraire
        return context.llm.renderer.render_refine(
            chunk=chunk,
            glossary=context.glossary,
            target_language=context.target_language,
            store=initial_translation,
            literary_context=literary_context,
        )
