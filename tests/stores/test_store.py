"""
Tests unitaires pour le module Store.

Ces tests vérifient le comportement de sauvegarde et récupération
des traductions sur disque.
"""

from pathlib import Path

from ebook_translator.segmentation.chunk import Chunk
from ebook_translator.stores import Store
from ebook_translator.translation.engine import build_translation_map

"Tests pour la classe Store."


def test_save_and_get(tmp_path: Path):
    """Test basique de sauvegarde et récupération."""
    store = Store(cache_dir=tmp_path)

    # Sauvegarder une traduction
    store.save("test.html", "0", "Bonjour")

    # Récupérer la traduction
    result = store.get("test.html", "0")

    assert result == "Bonjour"


def test_get_missing_translation(tmp_path: Path):
    """Test récupération d'une traduction inexistante."""
    store = Store(cache_dir=tmp_path)

    # Essayer de récupérer une traduction qui n'existe pas
    result = store.get("test.html", "999")

    assert result is None


def test_save_all(tmp_path: Path):
    """Test sauvegarde de plusieurs traductions en une fois."""
    store = Store(cache_dir=tmp_path)

    # Sauvegarder plusieurs traductions
    translations = {
        "0": "Bonjour",
        "1": "Monde",
        "2": "Python",
    }
    store.save_all("test.html", translations)

    # Vérifier toutes les traductions
    assert store.get("test.html", "0") == "Bonjour"
    assert store.get("test.html", "1") == "Monde"
    assert store.get("test.html", "2") == "Python"


def test_get_all(tmp_path: Path):
    """Test récupération de plusieurs traductions."""
    store = Store(cache_dir=tmp_path)

    # Sauvegarder des traductions
    store.save_all("test.html", {"0": "Un", "1": "Deux", "2": "Trois"})

    # Récupérer toutes les traductions
    results = store.get_all("test.html", ["0", "1", "2", "999"])

    assert results["0"] == "Un"
    assert results["1"] == "Deux"
    assert results["2"] == "Trois"
    assert results["999"] is None  # Traduction manquante


def test_save_and_get_from_chunk(tmp_path: Path, chunk: Chunk):
    """Test récupération des traductions pour un chunk."""
    store = Store(cache_dir=tmp_path)

    translated = {i: f"Traduction {i + 1}" for i in range(len(chunk.body))}

    savemap = build_translation_map(chunk, translated)
    # Sauvegarder des traductions pour le chunk
    for source_file, translations in savemap.items():
        store.save_all(source_file, translations)

    # Récupérer les traductions pour le chunk
    results, _ = store.get_from_chunk(chunk)

    assert results == translated


def test_clear(tmp_path: Path):
    """Test suppression du cache d'un fichier."""
    store = Store(cache_dir=tmp_path)

    # Sauvegarder une traduction
    store.save("test.html", "0", "Bonjour")
    assert store.get("test.html", "0") == "Bonjour"

    # Supprimer le cache
    store.clear("test.html")

    # Vérifier que le cache est vide
    assert store.get("test.html", "0") is None


def test_clear_all(tmp_path: Path):
    """Test suppression de tous les caches."""
    store = Store(cache_dir=tmp_path)

    # Sauvegarder plusieurs fichiers
    store.save("file1.html", "0", "Un")
    store.save("file2.html", "0", "Deux")

    # Supprimer tous les caches
    store.clear_all()

    # Vérifier que tous les caches sont vides
    assert store.get("file1.html", "0") is None
    assert store.get("file2.html", "0") is None


def test_cache_file_naming(tmp_path: Path):
    """Test que les fichiers de cache sont créés avec le bon nom."""
    store = Store(cache_dir=tmp_path)

    # Sauvegarder une traduction
    store.save("path/to/test.html", "0", "Test")

    # Vérifier qu'un fichier de cache a été créé
    cache_files = list(tmp_path.glob("*.json"))
    assert len(cache_files) == 1
    assert "path_to_test.html" in cache_files[0].name


def test_persistence(tmp_path: Path):
    """Test que les traductions sont persistées entre instances."""
    # Première instance : sauvegarder
    store1 = Store(cache_dir=tmp_path)
    store1.save("test.html", "0", "Persisté")

    # Deuxième instance : récupérer
    store2 = Store(cache_dir=tmp_path)
    result = store2.get("test.html", "0")

    assert result == "Persisté"


def test_corrupted_cache_handling(tmp_path: Path):
    """Test que le cache corrompu est géré correctement."""
    store = Store(cache_dir=tmp_path)

    # Créer un fichier de cache corrompu
    cache_file = store._get_cache_file(  # pyright: ignore[reportPrivateUsage]
        "test.html"
    )
    cache_file.write_text("{ invalid json }", encoding="utf-8")

    # Tenter de récupérer (devrait retourner un dict vide sans crasher)
    result = store.get("test.html", "0")

    assert result is None

    # Vérifier qu'une backup a été créée
    backup_files = list(tmp_path.glob("*.backup"))
    assert len(backup_files) == 1
