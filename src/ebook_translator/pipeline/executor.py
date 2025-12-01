"""
Exécuteur de phases.
"""

import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from tqdm import tqdm

from ebook_translator.logger import get_logger
from ebook_translator.pipeline.base import ExecutionMode
from ebook_translator.pipeline.context import ChunkContext, PhaseContext, PhaseStats
from ebook_translator.segmentation.segmentator import Chunk
from ebook_translator.validation.validation_queue import ValidationItem

if TYPE_CHECKING:
    from ebook_translator.pipeline.base import PhaseBase

logger = get_logger(__name__)


class PhaseExecutor:
    """
    Exécute une phase complète.

    Responsabilités:
    - Segmentation selon la configuration de la phase
    - Exécution parallel/sequential selon phase.execution_mode
    - Appel des hooks before/after
    - Gestion du cache
    - Soumission à ValidationWorkerPool

    Example:
        context = PhaseContext(...)
        executor = PhaseExecutor(InitialTranslationPhase, context)
        stats = executor.run()
    """

    def __init__(self, phase: "PhaseBase", context: PhaseContext):
        """
        Initialise l'exécuteur.

        Args:
            phase: Classe de phase à exécuter
            context: Contexte global de la phase
        """
        self.phase = phase
        self.context = context

        # Statistiques
        self.stats = PhaseStats(phase_name=phase.name)

    def run(self) -> PhaseStats:
        """
        Exécute la phase complète.

        Returns:
            PhaseStats avec les statistiques d'exécution
        """
        start_time = time.time()

        logger.info(f"=== Starting Phase: {self.phase.name} ===")
        logger.info(
            f"Configuration: max_tokens={self.phase.max_tokens}, "
            f"overlap={self.phase.overlap_ratio}, mode={self.phase.execution_mode.value}"
        )

        # 1. Hook before_phase
        self.phase.before_phase()

        # 2. Segmentation
        chunks = self.phase.get_chunks()
        self.stats.chunks_total = len(chunks)

        logger.info(f"Segmentation: {self.stats.chunks_total} chunks generated")

        # 3. Configuration ValidationWorkerPool
        self._configure_validation_pool()

        # 4. Exécution selon mode
        if (
            self.phase.execution_mode == ExecutionMode.PARALLEL
            or self.phase.get_worker_count() > 1
        ):
            self._run_parallel(chunks)
        else:
            self._run_sequential(chunks)

        # 5. Attendre validation complète
        logger.info("Waiting for validation to complete...")
        self.context.validation_pool.wait_completion()

        # 6. Hook after_phase
        self.stats.duration_seconds = time.time() - start_time
        self.phase.after_phase(self.stats)

        logger.info(
            f"=== Phase {self.phase.name} completed in {self.stats.duration_seconds:.1f}s ==="
        )
        logger.info(str(self.stats))

        return self.stats

    def _configure_validation_pool(self) -> None:
        """Configure le ValidationWorkerPool pour cette phase."""

        # Switch vers le store de cette phase
        store = self.context.store_manager.get_store(self.phase.store_key())
        # Update phase name dans le pool
        self.context.validation_pool.switch_phase(self.phase, store)

    def _process_chunk(self, chunk: Chunk) -> bool:
        """
        Traite un chunk (cache check + LLM + parse + submit).

        Args:
            chunk: Chunk à traiter

        Returns:
            True si traitement réussi, False sinon
        """
        try:
            # 1. Check cache
            cached_result, has_missing = self.phase.get_translation_cache(chunk)

            # 2. Hook before_chunk
            chunk_context = ChunkContext(
                target_language=self.context.target_language,
                llm=self.context.llm,
                store_manager=self.context.store_manager,
                glossary=self.context.glossary,
                phase_name=self.phase.name,
                chunk_index=chunk.index,
            )

            if not has_missing:
                # Chunk déjà en cache, on le soumet quand même pour validation
                # (peut avoir été invalidé ou nécessiter re-validation)
                self.stats.chunks_from_cache += 1
                self.context.validation_pool.submit(
                    ValidationItem(chunk, chunk_context, cached_result)
                )
                logger.debug(
                    f"✓ Chunk {chunk.index} loaded from cache ({self.phase.name})"
                )
                return True

            self.phase.before_chunk(chunk, chunk_context)

            # 3. Render prompt
            prompt = self.phase.render_prompt(chunk, chunk_context)

            # 4. LLM query
            context_str = f"{self.phase.name}_chunk_{chunk.index:03d}"
            source_content = self.phase.source_content(chunk, chunk_context)
            llm_config = self.phase.llm_config(chunk, chunk_context)
            llm_output = self.context.llm.query(
                prompt, source_content, log_name=context_str, config=llm_config
            )

            # 5. Parse
            translated_texts = self.phase.process_llm_response(
                chunk, llm_output, chunk_context
            )

            # 6. Hook after_chunk
            self.phase.after_chunk(chunk, translated_texts, chunk_context)

            # 7. Submit to validation
            self.context.validation_pool.submit(
                ValidationItem(chunk, chunk_context, translated_texts)
            )
            self.stats.chunks_translated += 1

            logger.debug(
                f"✅ Chunk {chunk.index} translated and submitted for validation ({self.phase.name})"
            )
            return True

        except Exception as e:
            logger.exception(
                f"Error processing chunk {chunk.index} in phase {self.phase.name}: {e}"
            )
            return False

    def _run_parallel(self, chunks: Sequence[Chunk]) -> None:
        """
        Exécution parallèle avec ThreadPoolExecutor.

        Args:
            chunks: Liste des chunks à traiter
        """
        max_workers = self.phase.get_worker_count()

        logger.info(f"Running in PARALLEL mode with {max_workers} workers")

        with (
            tqdm(
                total=len(chunks),
                desc=f"Phase {self.phase.name} (parallel)",
                unit="chunk",
                ncols=100,
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
            ) as pbar,
            ThreadPoolExecutor(max_workers=max_workers) as executor,
        ):
            # Soumettre toutes les tâches
            futures = {
                executor.submit(self._process_chunk, chunk): chunk for chunk in chunks
            }

            # Attendre completion
            for future in as_completed(futures):
                chunk = futures[future]
                try:
                    success = future.result()
                    if success:
                        self.stats.chunks_processed += 1
                    else:
                        pbar.write(f"⚠️ Chunk {chunk.index}: Processing failed")
                except KeyboardInterrupt:
                    pbar.write(f"\n❌ Phase {self.phase.name} interrupted by user")
                    raise
                except Exception as e:
                    logger.exception(f"Unexpected error for chunk {chunk.index}: {e}")
                    pbar.write(f"❌ Chunk {chunk.index}: Unexpected error")

                pbar.update(1)

    def _run_sequential(self, chunks: Sequence[Chunk]) -> None:
        """
        Exécution séquentielle (chunk par chunk).

        Args:
            chunks: Liste des chunks à traiter
        """
        logger.info("Running in SEQUENTIAL mode")

        with tqdm(
            total=len(chunks),
            desc=f"Phase {self.phase.name} (sequential)",
            unit="chunk",
            ncols=100,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
        ) as pbar:
            for chunk in chunks:
                try:
                    success = self._process_chunk(chunk)
                    self.context.validation_pool.wait_completion()
                    if success:
                        self.stats.chunks_processed += 1
                    else:
                        pbar.write(f"⚠️ Chunk {chunk.index}: Processing failed")
                except KeyboardInterrupt:
                    pbar.write(f"\n❌ Phase {self.phase.name} interrupted by user")
                    raise
                except Exception as e:
                    logger.exception(f"Unexpected error for chunk {chunk.index}: {e}")
                    pbar.write(f"❌ Chunk {chunk.index}: Unexpected error")

                pbar.update(1)
