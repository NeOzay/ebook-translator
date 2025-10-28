"""
Test de concurrence pour vérifier que Store._save_cache() et Store._load_cache()
sont thread-safe avec le système de Lock par fichier.

Ce test simule le scénario exact qui causait PermissionError sur Windows :
- Thread 1 (lecteur) : lit le cache pendant que Thread 2 écrit
- Thread 2 (écrivain) : écrit dans le cache pendant que Thread 1 lit
"""

import threading
import time
from pathlib import Path
from src.ebook_translator.store import Store

# Configuration
CACHE_DIR = Path("test_cache_concurrency")
TEST_DURATION = 5  # secondes
NUM_READERS = 3
NUM_WRITERS = 2

# Compteurs thread-safe
lock_stats = threading.Lock()
stats = {
    "reads": 0,
    "writes": 0,
    "errors": 0,
}


def reader_thread(store: Store, source_file: str, thread_id: int, stop_event: threading.Event):
    """Thread qui lit le cache en boucle."""
    while not stop_event.is_set():
        try:
            cache_file = store._get_cache_file(source_file)
            data = store._load_cache(cache_file)

            with lock_stats:
                stats["reads"] += 1

            # Simuler traitement
            time.sleep(0.01)

        except Exception as e:
            print(f"ERREUR lecture thread {thread_id}: {e}")
            with lock_stats:
                stats["errors"] += 1


def writer_thread(store: Store, source_file: str, thread_id: int, stop_event: threading.Event):
    """Thread qui écrit dans le cache en boucle."""
    counter = 0
    while not stop_event.is_set():
        try:
            cache_file = store._get_cache_file(source_file)

            # Écrire des données
            data = {str(i): f"Translation {counter}_{i}" for i in range(10)}
            store._save_cache(cache_file, data)

            with lock_stats:
                stats["writes"] += 1

            counter += 1

            # Simuler traitement
            time.sleep(0.02)

        except Exception as e:
            print(f"ERREUR ecriture thread {thread_id}: {e}")
            with lock_stats:
                stats["errors"] += 1


def test_concurrent_access():
    """Test principal de concurrence."""
    print("Test de concurrence Store (Locks par fichier)")
    print(f"  - Duree: {TEST_DURATION}s")
    print(f"  - Threads lecteurs: {NUM_READERS}")
    print(f"  - Threads ecrivains: {NUM_WRITERS}")
    print()

    # Créer répertoire de test
    CACHE_DIR.mkdir(exist_ok=True)

    # Créer Store
    store = Store(CACHE_DIR)
    source_file = "test_file.html"

    # Créer event d'arrêt
    stop_event = threading.Event()

    # Lancer threads
    threads = []

    # Lecteurs
    for i in range(NUM_READERS):
        t = threading.Thread(
            target=reader_thread,
            args=(store, source_file, i, stop_event),
            daemon=True,
        )
        t.start()
        threads.append(t)

    # Écrivains
    for i in range(NUM_WRITERS):
        t = threading.Thread(
            target=writer_thread,
            args=(store, source_file, i, stop_event),
            daemon=True,
        )
        t.start()
        threads.append(t)

    print("Test en cours...")

    # Attendre durée du test
    time.sleep(TEST_DURATION)

    # Arrêter threads
    stop_event.set()

    # Attendre fin des threads
    for t in threads:
        t.join(timeout=1.0)

    # Afficher résultats
    print()
    print("=" * 60)
    print("RESULTATS")
    print("=" * 60)
    print(f"  OK Lectures reussies: {stats['reads']}")
    print(f"  OK Ecritures reussies: {stats['writes']}")
    print(f"  ERREUR: {stats['errors']}")
    print()

    if stats["errors"] == 0:
        print("TEST REUSSI : Aucune erreur de concurrence detectee!")
        print("   Le systeme de Locks par fichier fonctionne correctement.")
    else:
        print("TEST ECHOUE : Des erreurs de concurrence ont ete detectees.")
        print("   Le systeme de Locks necessite des corrections.")

    # Nettoyage
    store.clear_all()
    CACHE_DIR.rmdir()

    return stats["errors"] == 0


if __name__ == "__main__":
    success = test_concurrent_access()
    exit(0 if success else 1)
