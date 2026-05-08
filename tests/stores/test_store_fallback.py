"""Tests pour le système de fallback du Store."""

from pathlib import Path

from ebook_translator.segmentation.chunk import Chunk
from ebook_translator.stores import Store
from ebook_translator.translation.engine import build_translation_map

# ── get() ─────────────────────────────────────────────────────────────────────


def test_get_fallback_returns_value_from_fallback_store(tmp_path: Path):
    """get() retourne la valeur du fallback si absente du store courant."""
    fallback = Store(tmp_path / "fallback")
    fallback.save("file.html", "0", "Bonjour")

    current = Store(tmp_path / "current", fallback=fallback)

    assert current.get("file.html", "0") == "Bonjour"


def test_get_current_store_takes_priority_over_fallback(tmp_path: Path):
    """get() retourne la valeur du store courant même si fallback en a une."""
    fallback = Store(tmp_path / "fallback")
    fallback.save("file.html", "0", "Fallback")

    current = Store(tmp_path / "current", fallback=fallback)
    current.save("file.html", "0", "Courant")

    assert current.get("file.html", "0") == "Courant"


def test_get_use_fallback_false_ignores_fallback(tmp_path: Path):
    """get(use_fallback=False) retourne None même si fallback a la valeur."""
    fallback = Store(tmp_path / "fallback")
    fallback.save("file.html", "0", "Bonjour")

    current = Store(tmp_path / "current", fallback=fallback)

    assert current.get("file.html", "0", use_fallback=False) is None


def test_get_returns_none_when_missing_everywhere(tmp_path: Path):
    """get() retourne None si absent du store courant ET du fallback."""
    fallback = Store(tmp_path / "fallback")
    current = Store(tmp_path / "current", fallback=fallback)

    assert current.get("file.html", "999") is None


def test_get_fallback_chain_two_levels(tmp_path: Path):
    """get() supporte une chaîne de fallback à 2 niveaux."""
    phase1 = Store(tmp_path / "phase1")
    phase1.save("file.html", "0", "Phase1")

    phase2 = Store(tmp_path / "phase2", fallback=phase1)
    phase3 = Store(tmp_path / "phase3", fallback=phase2)

    assert phase3.get("file.html", "0") == "Phase1"


def test_get_no_fallback_store_configured(tmp_path: Path):
    """get() retourne None si aucun fallback configuré et valeur absente."""
    store = Store(tmp_path)
    assert store.get("file.html", "0") is None


# ── get_all() ──────────────────────────────────────────────────────────────────


def test_get_all_fallback_fills_missing_values(tmp_path: Path):
    """get_all() remplace les valeurs manquantes par celles du fallback."""
    fallback = Store(tmp_path / "fallback")
    fallback.save_all("file.html", {"0": "Zero", "1": "Un"})

    current = Store(tmp_path / "current", fallback=fallback)
    current.save("file.html", "0", "Courant-Zero")

    result = current.get_all("file.html", ["0", "1", "2"])

    assert result["0"] == "Courant-Zero"
    assert result["1"] == "Un"
    assert result["2"] is None


def test_get_all_use_fallback_false(tmp_path: Path):
    """get_all(use_fallback=False) ne consulte pas le fallback."""
    fallback = Store(tmp_path / "fallback")
    fallback.save("file.html", "0", "Fallback")

    current = Store(tmp_path / "current", fallback=fallback)

    result = current.get_all("file.html", ["0"], use_fallback=False)

    assert result["0"] is None


# ── get_from_file() ────────────────────────────────────────────────────────────


def test_get_from_file_merges_fallback(tmp_path: Path):
    """get_from_file() merge fallback avec le store courant (courant prioritaire)."""
    fallback = Store(tmp_path / "fallback")
    fallback.save_all("file.html", {"0": "Fallback-0", "1": "Fallback-1"})

    current = Store(tmp_path / "current", fallback=fallback)
    current.save("file.html", "1", "Courant-1")

    result = current.get_from_file("file.html")

    assert result["0"] == "Fallback-0"
    assert result["1"] == "Courant-1"


def test_get_from_file_use_fallback_false(tmp_path: Path):
    """get_from_file(use_fallback=False) retourne seulement le store courant."""
    fallback = Store(tmp_path / "fallback")
    fallback.save("file.html", "0", "Fallback")

    current = Store(tmp_path / "current", fallback=fallback)

    result = current.get_from_file("file.html", use_fallback=False)

    assert "0" not in result


# ── get_from_chunk() ───────────────────────────────────────────────────────────


def test_get_from_chunk_has_missing_false_when_fallback_provides_value(
    tmp_path: Path, chunk: Chunk
):
    """has_missing=False si le fallback fournit toutes les valeurs."""
    fallback = Store(tmp_path / "fallback")
    translated = {i: f"Trad {i}" for i in range(len(chunk.body))}
    for source_file, translations in build_translation_map(chunk, translated).items():
        fallback.save_all(source_file, translations)

    current = Store(tmp_path / "current", fallback=fallback)
    result, has_missing = current.get_from_chunk(chunk)

    assert not has_missing
    assert result == translated


def test_get_from_chunk_use_fallback_false_ignores_fallback(
    tmp_path: Path, chunk: Chunk
):
    """get_from_chunk(use_fallback=False) → has_missing=True si seulement fallback a les valeurs."""
    fallback = Store(tmp_path / "fallback")
    translated = {i: f"Trad {i}" for i in range(len(chunk.body))}
    for source_file, translations in build_translation_map(chunk, translated).items():
        fallback.save_all(source_file, translations)

    current = Store(tmp_path / "current", fallback=fallback)
    _, has_missing = current.get_from_chunk(chunk, use_fallback=False)

    assert has_missing


def test_get_from_chunk_current_store_takes_priority(tmp_path: Path, chunk: Chunk):
    """get_from_chunk() retourne les valeurs du store courant en priorité."""
    fallback = Store(tmp_path / "fallback")
    current = Store(tmp_path / "current", fallback=fallback)

    fallback_translated = {i: f"Fallback {i}" for i in range(len(chunk.body))}
    current_translated = {i: f"Courant {i}" for i in range(len(chunk.body))}

    for source_file, translations in build_translation_map(
        chunk, fallback_translated
    ).items():
        fallback.save_all(source_file, translations)

    for source_file, translations in build_translation_map(
        chunk, current_translated
    ).items():
        current.save_all(source_file, translations)

    result, has_missing = current.get_from_chunk(chunk)

    assert not has_missing
    assert result == current_translated


def test_get_from_chunk_has_missing_true_when_absent_everywhere(
    tmp_path: Path, chunk: Chunk
):
    """has_missing=True si aucun store n'a les valeurs."""
    fallback = Store(tmp_path / "fallback")
    current = Store(tmp_path / "current", fallback=fallback)

    _, has_missing = current.get_from_chunk(chunk)

    assert has_missing
