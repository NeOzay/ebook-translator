from concurrent.futures import ThreadPoolExecutor, as_completed

from .store import Store
from .llm import LLM
from .segment import Segmentator
from .htmlpage import BilingualFormat
from .translation.engine import TranslationEngine


class TranslationWorker:
    def __init__(
        self,
        llm: LLM,
        target_language: str,
        store: Store,
        bilingual_format: BilingualFormat = BilingualFormat.SEPARATE_TAG,
    ):
        self.llm = llm
        self.target_language = target_language
        self.store = store
        self.bilingual_format = bilingual_format
        self.results = []
        self.engine = TranslationEngine(llm, store, target_language)

    def run(self, segments: Segmentator, max_threads_count):
        """Soumet toutes les traductions et attend les résultats."""
        futures = []

        with ThreadPoolExecutor(max_workers=max_threads_count) as executor:
            futures = [
                executor.submit(
                    lambda chunk=chunk: (
                        chunk,
                        self.engine.translate_chunk(
                            chunk, bilingual_format=self.bilingual_format
                        ),
                    )
                )
                for chunk in segments.get_all_segments()
            ]

        # Attendre toutes les futures
        for f in as_completed(futures):
            result = f.result()
