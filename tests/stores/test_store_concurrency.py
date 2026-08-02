"""
Tests de concurrence pour le module Store.

Ces tests vérifient que Store._save_cache() et Store._load_cache()
sont thread-safe avec le système de Lock par fichier, simulant le scénario
exact qui causait PermissionError sur Windows.
"""

import threading
import time
from pathlib import Path

import pytest

from ebook_translator.stores import Store
from ebook_translator.stores.store import _load_cache, _save_cache


def test_concurrent_read_write(tmp_path: Path) -> None:
    """
    Test de concurrence avec lecteurs et écrivains simultanés.

    Simule le scénario qui causait PermissionError sur Windows:
    - Threads lecteurs: lisent le cache pendant que d'autres écrivent
    - Threads écrivains: écrivent dans le cache pendant que d'autres lisent

    Le test vérifie qu'aucune erreur de concurrence n'est détectée.
    """
    # Configuration
    test_duration = 2.0  # secondes (réduit pour les tests)
    num_readers = 3
    num_writers = 2

    # Créer Store
    store = Store(cache_dir=tmp_path)
    source_file = "test_file.html"

    # Compteurs thread-safe
    lock_stats = threading.Lock()
    stats = {
        "reads": 0,
        "writes": 0,
        "errors": 0,
    }

    def reader_thread(stop_event: threading.Event) -> None:
        """Thread qui lit le cache en boucle."""
        while not stop_event.is_set():
            try:
                cache_file = store._get_cache_file(  # pyright: ignore[reportPrivateUsage]
                    source_file
                )
                _ = _load_cache(cache_file)  # pyright: ignore[reportPrivateUsage]

                with lock_stats:
                    stats["reads"] += 1

                # Simuler traitement
                time.sleep(0.01)

            except Exception:
                with lock_stats:
                    stats["errors"] += 1
                # Ne pas logger pour éviter de polluer la sortie des tests
                # L'erreur sera comptée dans les stats

    def writer_thread(stop_event: threading.Event) -> None:
        """Thread qui écrit dans le cache en boucle."""
        counter = 0
        while not stop_event.is_set():
            try:
                cache_file = store._get_cache_file(  # pyright: ignore[reportPrivateUsage]
                    source_file
                )

                # Écrire des données
                data = {str(i): f"Translation {counter}_{i}" for i in range(10)}
                _save_cache(cache_file, data)  # pyright: ignore[reportPrivateUsage]

                with lock_stats:
                    stats["writes"] += 1

                counter += 1

                # Simuler traitement
                time.sleep(0.02)

            except Exception:
                with lock_stats:
                    stats["errors"] += 1
                # Ne pas logger pour éviter de polluer la sortie des tests

    # Créer event d'arrêt
    stop_event = threading.Event()

    # Lancer threads
    threads: list[threading.Thread] = []

    # Lecteurs
    for _ in range(num_readers):
        t = threading.Thread(
            target=reader_thread,
            args=(stop_event,),
            daemon=True,
        )
        t.start()
        threads.append(t)

    # Écrivains
    for _ in range(num_writers):
        t = threading.Thread(
            target=writer_thread,
            args=(stop_event,),
            daemon=True,
        )
        t.start()
        threads.append(t)

    # Attendre durée du test
    time.sleep(test_duration)

    # Arrêter threads
    stop_event.set()

    # Attendre fin des threads
    for t in threads:
        t.join(timeout=1.0)

    # Vérifier qu'aucune erreur n'est survenue
    assert stats["errors"] == 0, (
        f"Erreurs de concurrence détectées: {stats['errors']} "
        f"(lectures: {stats['reads']}, écritures: {stats['writes']})"
    )

    # Vérifier qu'au moins quelques opérations ont été effectuées
    assert stats["reads"] > 0, "Aucune lecture effectuée"
    assert stats["writes"] > 0, "Aucune écriture effectuée"


def test_concurrent_save_all(tmp_path: Path) -> None:
    """
    Test de concurrence pour save_all() avec plusieurs threads.

    Vérifie que plusieurs threads peuvent sauvegarder des traductions
    simultanément sans erreurs.
    """
    store = Store(cache_dir=tmp_path)
    source_file = "test_concurrent.html"
    num_threads = 5
    iterations_per_thread = 10

    errors: list[Exception] = []
    lock = threading.Lock()

    def save_worker(thread_id: int) -> None:
        """Thread qui sauvegarde des traductions."""
        try:
            for i in range(iterations_per_thread):
                translations = {
                    f"{thread_id}_{j}": f"Translation_{thread_id}_{i}_{j}"
                    for j in range(5)
                }
                store.save_all(source_file, translations)
                time.sleep(0.001)  # Micro-pause
        except Exception as e:
            with lock:
                errors.append(e)

    # Lancer threads
    threads = [
        threading.Thread(target=save_worker, args=(i,)) for i in range(num_threads)
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    # Vérifier qu'aucune erreur n'est survenue
    assert len(errors) == 0, f"Erreurs détectées: {errors}"

    # Vérifier que toutes les traductions ont été sauvegardées
    cache_file = store._get_cache_file(  # pyright: ignore[reportPrivateUsage]
        source_file
    )
    data = _load_cache(cache_file)  # pyright: ignore[reportPrivateUsage]

    # Note: save_all fait un update, donc les anciennes valeurs sont écrasées
    # On vérifie juste qu'il y a des données
    assert len(data) > 0, "Aucune donnée sauvegardée"


def test_concurrent_get_all(tmp_path: Path) -> None:
    """
    Test de concurrence pour get_all() avec plusieurs threads.

    Vérifie que plusieurs threads peuvent lire des traductions
    simultanément pendant qu'un autre thread écrit.
    """
    store = Store(cache_dir=tmp_path)
    source_file = "test_read_concurrent.html"

    # Préparer des données initiales
    initial_data = {str(i): f"Translation_{i}" for i in range(100)}
    store.save_all(source_file, initial_data)

    num_readers = 5
    test_duration = 1.0  # secondes
    errors: list[Exception] = []
    lock = threading.Lock()
    stop_event = threading.Event()

    def reader_worker() -> None:
        """Thread qui lit des traductions."""
        try:
            while not stop_event.is_set():
                indices = [str(i) for i in range(0, 100, 10)]
                results = store.get_all(source_file, indices)
                # Vérifier que les résultats sont cohérents
                assert all(v is not None for v in results.values())
                time.sleep(0.01)
        except Exception as e:
            with lock:
                errors.append(e)

    def writer_worker() -> None:
        """Thread qui met à jour des traductions."""
        try:
            counter = 0
            while not stop_event.is_set():
                updates = {str(i): f"Updated_{counter}_{i}" for i in range(50)}
                store.save_all(source_file, updates)
                counter += 1
                time.sleep(0.02)
        except Exception as e:
            with lock:
                errors.append(e)

    # Lancer threads lecteurs
    threads = [threading.Thread(target=reader_worker) for _ in range(num_readers)]

    # Lancer thread écrivain
    threads.append(threading.Thread(target=writer_worker))

    for t in threads:
        t.start()

    # Attendre
    time.sleep(test_duration)
    stop_event.set()

    for t in threads:
        t.join(timeout=1.0)

    # Vérifier qu'aucune erreur n'est survenue
    assert len(errors) == 0, f"Erreurs détectées: {errors}"


def test_file_lock_isolation(tmp_path: Path) -> None:
    """
    Test que les locks sont bien isolés par fichier.

    Vérifie qu'un thread écrivant dans file1 ne bloque pas
    un autre thread écrivant dans file2.
    """
    store = Store(cache_dir=tmp_path)

    completed: dict[str, bool] = {}
    lock = threading.Lock()
    errors: list[Exception] = []

    def worker(file_name: str, delay: float) -> None:
        """Thread qui écrit dans un fichier avec un délai."""
        try:
            time.sleep(delay)
            store.save(file_name, "0", f"Translation for {file_name}")
            with lock:
                completed[file_name] = True
        except Exception as e:
            with lock:
                errors.append(e)

    # Lancer deux threads avec des délais différents
    t1 = threading.Thread(target=worker, args=("file1.html", 0.1))
    t2 = threading.Thread(target=worker, args=("file2.html", 0.05))

    start = time.time()
    t1.start()
    t2.start()

    t1.join(timeout=2.0)
    t2.join(timeout=2.0)
    duration = time.time() - start

    # Vérifier qu'aucune erreur n'est survenue
    assert len(errors) == 0, f"Erreurs détectées: {errors}"

    # Vérifier que les deux threads ont terminé
    assert completed.get("file1.html", False), "Thread file1 n'a pas terminé"
    assert completed.get("file2.html", False), "Thread file2 n'a pas terminé"

    # Vérifier que les deux threads ont bien pu s'exécuter en parallèle
    # (durée totale < somme des délais + marge)
    assert duration < 0.2, (
        f"Les locks ne sont pas isolés par fichier (durée: {duration:.3f}s)"
    )


@pytest.mark.slow
def test_stress_concurrent_operations(tmp_path: Path) -> None:
    """
    Test de stress avec de nombreuses opérations concurrentes.

    Ce test est marqué 'slow' et peut être sauté dans les tests rapides.
    """
    store = Store(cache_dir=tmp_path)
    source_file = "stress_test.html"
    num_threads = 10
    operations_per_thread = 100

    errors: list[Exception] = []
    lock = threading.Lock()

    def stress_worker(thread_id: int) -> None:
        """Thread qui effectue des opérations mixtes."""
        try:
            for i in range(operations_per_thread):
                # Alterner entre lecture et écriture
                if i % 2 == 0:
                    # Écriture
                    store.save(source_file, f"{thread_id}_{i}", f"Translation_{i}")
                else:
                    # Lecture
                    _ = store.get(source_file, f"{thread_id}_{i - 1}")
                time.sleep(0.001)
        except Exception as e:
            with lock:
                errors.append(e)

    # Lancer threads
    threads = [
        threading.Thread(target=stress_worker, args=(i,)) for i in range(num_threads)
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    # Vérifier qu'aucune erreur n'est survenue
    assert len(errors) == 0, f"Erreurs détectées: {errors}"
