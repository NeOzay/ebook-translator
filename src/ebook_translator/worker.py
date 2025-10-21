from concurrent.futures import ThreadPoolExecutor, as_completed
from time import sleep

from tqdm import tqdm

from .store import Store
from .llm import LLM
from .segment import Segmentator
from .htmlpage import BilingualFormat
from .translation.engine import TranslationEngine
from .correction.retry_engine import RetryEngine
from .logger import get_logger

logger = get_logger(__name__)


class TranslationWorker:
    def __init__(
        self,
        llm: LLM,
        target_language: str,
        store: Store,
        bilingual_format: BilingualFormat = BilingualFormat.SEPARATE_TAG,
        user_prompt: str | None = None,
        auto_correct_errors: bool = True,
        max_correction_retries: int = 2,
    ):
        self.llm = llm
        self.target_language = target_language
        self.store = store
        self.bilingual_format = bilingual_format
        self.user_prompt = user_prompt
        self.auto_correct_errors = auto_correct_errors

        # Créer le retry engine si auto_correct activé
        retry_engine = None
        if auto_correct_errors:
            retry_engine = RetryEngine(llm, max_retries=max_correction_retries)

        # Initialiser le moteur de traduction avec retry_engine
        self.engine = TranslationEngine(llm, store, target_language, retry_engine)

    def run(self, segments: Segmentator, max_threads_count: int):
        """Soumet toutes les traductions et attend les résultats."""
        # Convertir les segments en liste pour connaître le nombre total
        all_segments = list(segments.get_all_segments())
        total_segments = len(all_segments)

        self._run_parallel(all_segments, total_segments, max_threads_count)


    def _run_parallel(self, all_segments: list, total_segments: int, max_threads_count: int):
        """Exécute les traductions en parallèle avec retry automatique."""
        errors_count = 0
        skipped_count = 0

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

                    except KeyboardInterrupt:
                        pbar.write("\n❌ Traduction interrompue par l'utilisateur")
                        raise

                    except ValueError as e:
                        # Erreur de validation (après échec de retry si activé)
                        error_msg = str(e)
                        logger.error(f"Erreur de validation : {error_msg}")
                        errors_count += 1

                        if len(error_msg) > 500:
                            short_msg = (
                                error_msg[:500]
                                + "\n... (voir logs pour détails complets)"
                            )
                            pbar.write(
                                f"\n{'='*60}\n❌ ERREUR DE VALIDATION #{errors_count}\n{'='*60}\n{short_msg}\n{'='*60}\n"
                            )
                        else:
                            pbar.write(
                                f"\n{'='*60}\n❌ ERREUR DE VALIDATION #{errors_count}\n{'='*60}\n{error_msg}\n{'='*60}\n"
                            )

                    except Exception as e:
                        # Autres erreurs inattendues
                        logger.exception(f"Erreur inattendue : {e}")
                        errors_count += 1
                        pbar.write(
                            f"\n❌ ERREUR INATTENDUE #{errors_count}: {type(e).__name__}: {e}\n"
                        )

                # Récupérer les statistiques de correction depuis l'engine
                corrected_count = self.engine.corrected_count

                # Résumé final
                self._print_summary(pbar, errors_count, corrected_count, skipped_count)

    def _print_summary(self, pbar, errors_count: int, corrected_count: int, skipped_count: int):
        """Affiche le résumé final de la traduction."""
        if errors_count > 0 or corrected_count > 0 or skipped_count > 0:
            pbar.write(f"\n{'='*60}")
            pbar.write(f"📊 Résumé de la traduction:")
            if corrected_count > 0:
                pbar.write(f"   ✅ Corrections automatiques: {corrected_count}")
            if errors_count > 0:
                pbar.write(f"   ❌ Erreurs: {errors_count}")
            if skipped_count > 0:
                pbar.write(f"   ⏭️  Segments ignorés: {skipped_count}")
            if errors_count > 0 or corrected_count > 0:
                pbar.write(
                    f"   📁 Consultez les logs dans 'logs/' pour plus de détails"
                )
            pbar.write(f"{'='*60}\n")
