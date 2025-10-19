from concurrent.futures import ThreadPoolExecutor, as_completed
from time import sleep

from tqdm import tqdm

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
        user_prompt: str | None = None,
    ):
        self.llm = llm
        self.target_language = target_language
        self.store = store
        self.bilingual_format = bilingual_format
        self.user_prompt = user_prompt
        self.engine = TranslationEngine(llm, store, target_language)

    def run(self, segments: Segmentator, max_threads_count: int):
        """Soumet toutes les traductions et attend les résultats."""
        # Convertir les segments en liste pour connaître le nombre total
        all_segments = list(segments.get_all_segments())
        total_segments = len(all_segments)

        # Attendre toutes les futures avec barre de progression
        with tqdm(
            total=total_segments,
            desc="Traduction des segments",
            unit="segment",
            ncols=100,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
        ) as pbar:
            with ThreadPoolExecutor(max_workers=max_threads_count) as executor:
                # Soumettre toutes les tâches et collecter les futures
                futures = []
                for chunk in all_segments:
                    future = executor.submit(
                        self.engine.translate_chunk,
                        chunk,
                        bar=pbar,
                        bilingual_format=self.bilingual_format,
                        user_prompt=self.user_prompt,
                    )
                    futures.append(future)

                # Attendre que toutes les traductions soient terminées
                for future in as_completed(futures):
                    try:
                        future.result()  # Récupère le résultat ou propage l'exception
                    except Exception as e:
                        # Logger l'erreur mais continuer avec les autres traductions
                        pbar.write(
                            f"❌ Erreur lors de la traduction d'un segment : {e}"
                        )
