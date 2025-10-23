"""Test simple du CorrectionWorkerPool"""
import sys
import time
from pathlib import Path

from src.ebook_translator.correction.error_queue import ErrorQueue
from src.ebook_translator.correction.correction_worker_pool import CorrectionWorkerPool
from src.ebook_translator.llm import LLM
from src.ebook_translator.store import Store

def main():
    # TEST 1
    print("[TEST 1] Creation du pool avec 3 workers...", flush=True)
    error_queue = ErrorQueue(maxsize=10)
    llm = LLM(model_name="deepseek-chat", url="https://api.deepseek.com")
    store = Store(cache_dir=Path("test_cache"))

    pool = CorrectionWorkerPool(
        error_queue=error_queue,
        llm=llm,
        store=store,
        target_language="fr",
        num_workers=3,
    )

    print(f"[OK] Pool cree: {pool.num_workers} workers", flush=True)

    # TEST 2
    print("[TEST 2] Demarrage du pool...", flush=True)
    pool.start()
    time.sleep(0.5)

    stats = pool.get_aggregated_statistics()
    print(f"[OK] Workers actifs: {stats['workers_alive']}/{stats['total_workers']}", flush=True)
    assert stats["workers_alive"] == 3, f"Expected 3 alive, got {stats['workers_alive']}"

    # TEST 3
    print("[TEST 3] Statistiques agregees...", flush=True)
    pool.workers[0].corrected_count = 5
    pool.workers[1].corrected_count = 3
    pool.workers[2].corrected_count = 7

    stats = pool.get_aggregated_statistics()
    print(f"[OK] Corrected agrege: {stats['corrected']} (attendu: 15)", flush=True)
    assert stats["corrected"] == 15, f"Expected 15, got {stats['corrected']}"

    # TEST 4
    print("[TEST 4] Arret du pool...", flush=True)
    stopped = pool.stop(timeout=5.0)
    assert stopped, "Pool should stop successfully"

    stats = pool.get_aggregated_statistics()
    print(f"[OK] Workers actifs apres arret: {stats['workers_alive']}/{stats['total_workers']}", flush=True)
    assert stats["workers_alive"] == 0, "All workers should be stopped"

    print("\n[SUCCESS] Tous les tests reussis!", flush=True)
    print("  - Creation et gestion de 3 workers en parallele", flush=True)
    print("  - Agregation correcte des statistiques", flush=True)
    print("  - Arret propre de tous les workers", flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[ERREUR] {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
