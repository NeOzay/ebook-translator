"""Résolution de la matière auditée."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from ebook_translator.audit.source import AuditSource, AuditSourceError
from ebook_translator.pipeline.base import PhaseBase, PhaseName

from .conftest import terme


class TestResolve:
    """Résolution d'un cache et de son EPUB source."""

    def test_cache_inexistant_leve(self, tmp_path: Path) -> None:
        with pytest.raises(AuditSourceError, match="Cache introuvable"):
            _ = AuditSource.resolve(tmp_path / "absent")

    def test_epub_explicite_inexistant_leve(self, cache_dir: Path) -> None:
        with pytest.raises(AuditSourceError, match="EPUB introuvable"):
            _ = AuditSource.resolve(cache_dir, cache_dir / "absent.epub")

    def test_epub_deduit_du_repertoire_parent(self, cache_dir: Path) -> None:
        attendu = cache_dir.parent / "Mon Livre.epub"
        attendu.write_bytes(b"PK\x03\x04")

        source = AuditSource.resolve(cache_dir)

        assert source.epub_path == attendu

    def test_epub_traduit_ecarte(self, cache_dir: Path) -> None:
        """La sortie du pipeline ne doit jamais être prise pour la source."""
        (cache_dir.parent / "Mon Livre [traduit].epub").write_bytes(b"PK\x03\x04")

        source = AuditSource.resolve(cache_dir)

        assert source.epub_path is None

    def test_sans_epub_le_texte_source_est_vide(self, cache_dir: Path) -> None:
        source = AuditSource.resolve(cache_dir)

        assert source.source_text == ""


class TestPhaseDir:
    """Accès aux dossiers de phase."""

    def test_phase_absente_leve_en_listant_les_presentes(self, cache_dir: Path) -> None:
        (cache_dir / str(PhaseName.INITIAL)).mkdir()
        source = AuditSource.resolve(cache_dir)

        with pytest.raises(AuditSourceError, match="initial"):
            _ = source.phase_dir(PhaseName.GLOSSARY)

    def test_available_phases_trie(self, cache_dir: Path) -> None:
        (cache_dir / str(PhaseName.INITIAL)).mkdir()
        (cache_dir / str(PhaseName.GLOSSARY)).mkdir()

        assert AuditSource.resolve(cache_dir).available_phases() == (
            "glossary",
            "initial",
        )


class TestByteStorePayloads:
    """Lecture du store v2."""

    def test_fusionne_les_fichiers(
        self, cache_dir: Path, write_glossary_chunks: Callable[..., Path]
    ) -> None:
        _ = write_glossary_chunks({"0_aaa": [terme("john", "john")]})
        source = AuditSource.resolve(cache_dir)

        charges = source.byte_store_payloads(PhaseName.GLOSSARY)

        assert list(charges) == ["0_aaa"]
        assert json.loads(charges["0_aaa"])[0]["terme"] == "john"

    def test_v2_absent_rend_un_mapping_vide(self, cache_dir: Path) -> None:
        (cache_dir / str(PhaseName.GLOSSARY)).mkdir()
        source = AuditSource.resolve(cache_dir)

        assert source.byte_store_payloads(PhaseName.GLOSSARY) == {}

    def test_fichier_illisible_ignore(self, cache_dir: Path) -> None:
        dossier = cache_dir / str(PhaseName.GLOSSARY) / PhaseBase.BYTE_STORE_SUBDIR
        dossier.mkdir(parents=True)
        _ = (dossier / "casse.json").write_text("{pas du json", encoding="utf-8")
        source = AuditSource.resolve(cache_dir)

        assert source.byte_store_payloads(PhaseName.GLOSSARY) == {}


class TestMarkdownDocuments:
    """Lecture des Markdown de revue."""

    def test_indexe_par_nom_de_fichier(self, cache_dir: Path) -> None:
        dossier = cache_dir / str(PhaseName.GLOSSARY)
        dossier.mkdir()
        _ = (dossier / "chunk 0.md").write_text("| a |", encoding="utf-8")
        source = AuditSource.resolve(cache_dir)

        assert source.markdown_documents(PhaseName.GLOSSARY) == {"chunk 0": "| a |"}
