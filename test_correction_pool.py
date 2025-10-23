"""
Test du CorrectionWorkerPool avec plusieurs workers en parallèle.

Ce test vérifie que le pool démarre/arrête correctement plusieurs workers
et que les statistiques sont agrégées correctement.
"""

import time
from pathlib import Path

from src.ebook_translator.correction.error_queue import ErrorQueue
from src.ebook_translator.correction.correction_worker_pool import CorrectionWorkerPool
from src.ebook_translator.llm import LLM
from src.ebook_translator.store import Store


def test_pool_basic():
    """Test basique : création, démarrage, arrêt du pool."""
    print("\n" + "=" * 60)
    print("TEST 1 : Création et gestion du pool")
    print("=" * 60)

    # Setup
    error_queue = ErrorQueue(maxsize=10)
    llm = LLM(
        model_name="deepseek-chat",
        url="https://api.deepseek.com",
    )
    store = Store(cache_dir=Path("test_cache"))
    target_language = "fr"

    # Créer pool avec 3 workers
    pool = CorrectionWorkerPool(
        error_queue=error_queue,
        llm=llm,
        store=store,
        target_language=target_language,
        num_workers=3,
    )

    print(f"✅ Pool créé: {pool.num_workers} workers")

    # Démarrer
    pool.start()
    time.sleep(0.5)  # Laisser les threads démarrer

    # Vérifier que les workers sont actifs
    stats = pool.get_aggregated_statistics()
    print(f"✅ Workers actifs: {stats['workers_alive']}/{stats['total_workers']}")
    print(f"   Statistiques: {stats}")

    assert stats["workers_alive"] == 3, f"Expected 3 alive, got {stats['workers_alive']}"
    assert stats["corrected"] == 0, "Should have 0 corrected initially"
    assert stats["failed"] == 0, "Should have 0 failed initially"

    # Arrêter
    stopped = pool.stop(timeout=5.0)
    assert stopped, "Pool should stop successfully"
    print("✅ Pool arrêté avec succès")

    # Vérifier que les workers sont arrêtés
    stats = pool.get_aggregated_statistics()
    print(f"✅ Workers actifs après arrêt: {stats['workers_alive']}/{stats['total_workers']}")
    assert stats["workers_alive"] == 0, "All workers should be stopped"


def test_pool_switch_store():
    """Test du switch de store sur tous les workers."""
    print("\n" + "=" * 60)
    print("TEST 2 : Switch de store")
    print("=" * 60)

    # Setup
    error_queue = ErrorQueue(maxsize=10)
    llm = LLM(model_name="deepseek-chat", url="https://api.deepseek.com")
    store1 = Store(cache_dir=Path("test_cache_1"))
    store2 = Store(cache_dir=Path("test_cache_2"))

    # Créer pool avec 2 workers
    pool = CorrectionWorkerPool(
        error_queue=error_queue,
        llm=llm,
        store=store1,
        target_language="fr",
        num_workers=2,
    )

    pool.start()
    time.sleep(0.5)

    print(f"✅ Pool démarré avec store 1 (id={id(store1)})")

    # Switch vers store2
    pool.switch_all_stores(store2)
    print(f"✅ Pool basculé vers store 2 (id={id(store2)})")

    # Vérifier que tous les workers ont le nouveau store
    for worker in pool.workers:
        assert worker.store is store2, f"Worker {worker.worker_id} should have store2"
    print(f"✅ Tous les workers utilisent le nouveau store")

    # Cleanup
    pool.stop(timeout=5.0)


def test_pool_statistics():
    """Test de l'agrégation des statistiques."""
    print("\n" + "=" * 60)
    print("TEST 3 : Agrégation des statistiques")
    print("=" * 60)

    # Setup
    error_queue = ErrorQueue(maxsize=10)
    llm = LLM(model_name="deepseek-chat", url="https://api.deepseek.com")
    store = Store(cache_dir=Path("test_cache"))

    # Créer pool avec 3 workers
    pool = CorrectionWorkerPool(
        error_queue=error_queue,
        llm=llm,
        store=store,
        target_language="fr",
        num_workers=3,
    )

    pool.start()
    time.sleep(0.5)

    # Simuler quelques corrections (manuellement pour le test)
    pool.workers[0].corrected_count = 5
    pool.workers[1].corrected_count = 3
    pool.workers[2].corrected_count = 7

    pool.workers[0].failed_count = 1
    pool.workers[1].failed_count = 2
    pool.workers[2].failed_count = 0

    # Récupérer stats agrégées
    stats = pool.get_aggregated_statistics()

    print(f"✅ Stats agrégées:")
    print(f"   • Corrected: {stats['corrected']} (attendu: 15)")
    print(f"   • Failed: {stats['failed']} (attendu: 3)")
    print(f"   • Workers alive: {stats['workers_alive']}/3")

    assert stats["corrected"] == 15, f"Expected 15, got {stats['corrected']}"
    assert stats["failed"] == 3, f"Expected 3, got {stats['failed']}"
    assert stats["workers_alive"] == 3, "All workers should be alive"

    # Vérifier les stats par worker
    by_worker = stats["by_worker"]
    assert len(by_worker) == 3, "Should have 3 workers"
    print(f"✅ Stats par worker:")
    for worker_stats in by_worker:
        print(f"   • Worker-{worker_stats['worker_id']}: "
              f"corrected={worker_stats['corrected']}, "
              f"failed={worker_stats['failed']}")

    # Cleanup
    pool.stop(timeout=5.0)


def test_pool_with_one_worker():
    """Test rétrocompatibilité : pool avec 1 seul worker."""
    print("\n" + "=" * 60)
    print("TEST 4 : Pool avec 1 seul worker (rétrocompatibilité)")
    print("=" * 60)

    # Setup
    error_queue = ErrorQueue(maxsize=10)
    llm = LLM(model_name="deepseek-chat", url="https://api.deepseek.com")
    store = Store(cache_dir=Path("test_cache"))

    # Créer pool avec 1 worker (comme l'ancien comportement)
    pool = CorrectionWorkerPool(
        error_queue=error_queue,
        llm=llm,
        store=store,
        target_language="fr",
        num_workers=1,
    )

    pool.start()
    time.sleep(0.5)

    stats = pool.get_aggregated_statistics()
    print(f"✅ Pool avec 1 worker créé et démarré")
    print(f"   • Workers actifs: {stats['workers_alive']}/1")

    assert stats["workers_alive"] == 1, "Should have 1 worker alive"
    assert stats["total_workers"] == 1, "Should have 1 total worker"

    # Cleanup
    pool.stop(timeout=5.0)
    print("✅ Rétrocompatibilité OK")


if __name__ == "__main__":
    try:
        test_pool_basic()
        test_pool_switch_store()
        test_pool_statistics()
        test_pool_with_one_worker()

        print("\n" + "=" * 60)
        print("✅ TOUS LES TESTS RÉUSSIS")
        print("=" * 60)
        print("\nLe CorrectionWorkerPool fonctionne correctement :")
        print("  • Création et gestion de N workers en parallèle")
        print("  • Switch de store sur tous les workers")
        print("  • Agrégation des statistiques")
        print("  • Rétrocompatibilité avec 1 worker")

    except AssertionError as e:
        print(f"\n❌ TEST ÉCHOUÉ: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
