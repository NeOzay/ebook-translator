"""Rendu du répertoire d'audit et ligne de commande."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from ebook_translator.audit.__main__ import main
from ebook_translator.audit.findings import (
    AuditFindings,
    Metric,
    Observation,
    Sample,
)
from ebook_translator.audit.report import (
    MANIFEST_NAME,
    METRICS_NAME,
    REPORT_NAME,
    SPEC_NAME,
    write_audit,
)
from ebook_translator.audit.source import AuditSource
from ebook_translator.pipeline.base import PhaseName

from .conftest import terme

FINDINGS = AuditFindings(
    phase=PhaseName.GLOSSARY,
    spec_name="glossary",
    metrics=(
        Metric("Termes uniques", 48, "termes"),
        Metric("Densité", 7.72, "termes / 1000 mots", detail="Aucun seuil."),
    ),
    observations=(
        Observation(
            category="rare",
            title="Écart rare",
            description="Peu fréquent.",
            count=1,
            samples=(Sample("a", "vu une fois"),),
        ),
        Observation(
            category="frequent",
            title="Écart fréquent",
            description="Très fréquent.",
            count=28,
            samples=(Sample("b", "vu | souvent", context="ici"),),
        ),
    ),
    notes=("Une limite connue.",),
)


class TestWriteAudit:
    """Contenu du répertoire produit."""

    def test_ecrit_les_quatre_fichiers(self, cache_dir: Path, tmp_path: Path) -> None:
        sortie = write_audit(
            FINDINGS, AuditSource.resolve(cache_dir), tmp_path / "audit"
        )

        for nom in (REPORT_NAME, METRICS_NAME, SPEC_NAME, MANIFEST_NAME):
            assert (sortie / nom).is_file()

    def test_spec_recopiee_et_non_referencee(
        self, cache_dir: Path, tmp_path: Path
    ) -> None:
        """L'agent démarre à contexte vide : il ne doit rien avoir à chercher."""
        sortie = write_audit(
            FINDINGS, AuditSource.resolve(cache_dir), tmp_path / "audit"
        )

        spec = (sortie / SPEC_NAME).read_text(encoding="utf-8")
        assert "Cahier des charges — phase glossaire" in spec

    def test_catalogue_classe_par_effectif_decroissant(
        self, cache_dir: Path, tmp_path: Path
    ) -> None:
        sortie = write_audit(
            FINDINGS, AuditSource.resolve(cache_dir), tmp_path / "audit"
        )

        rapport = (sortie / REPORT_NAME).read_text(encoding="utf-8")
        assert rapport.index("`frequent`") < rapport.index("`rare`")

    def test_pipe_echappe_dans_les_cellules(
        self, cache_dir: Path, tmp_path: Path
    ) -> None:
        sortie = write_audit(
            FINDINGS, AuditSource.resolve(cache_dir), tmp_path / "audit"
        )

        rapport = (sortie / REPORT_NAME).read_text(encoding="utf-8")
        assert "vu \\| souvent" in rapport

    def test_limites_de_mesure_rendues(self, cache_dir: Path, tmp_path: Path) -> None:
        sortie = write_audit(
            FINDINGS, AuditSource.resolve(cache_dir), tmp_path / "audit"
        )

        assert "Une limite connue." in (sortie / REPORT_NAME).read_text(
            encoding="utf-8"
        )

    def test_manifeste_porte_chiffres_et_provenance(
        self, cache_dir: Path, tmp_path: Path
    ) -> None:
        sortie = write_audit(
            FINDINGS, AuditSource.resolve(cache_dir), tmp_path / "audit"
        )

        manifeste = json.loads((sortie / MANIFEST_NAME).read_text(encoding="utf-8"))
        assert manifeste["phase"] == "glossary"
        assert manifeste["cache_dir"] == str(cache_dir)
        assert manifeste["metrics"]["Termes uniques"] == 48
        assert manifeste["observations"] == {"frequent": 28, "rare": 1}

    def test_categorie_sans_cas_reste_affichee(
        self, cache_dir: Path, tmp_path: Path
    ) -> None:
        """Zéro cas est un résultat : le faire disparaître le rendrait indiscernable
        d'une catégorie non mesurée."""
        findings = AuditFindings(
            phase=PhaseName.GLOSSARY,
            spec_name="glossary",
            observations=(
                Observation(
                    category="vide",
                    title="Rien à signaler",
                    description="Cherché, non trouvé.",
                    count=0,
                ),
            ),
        )

        sortie = write_audit(
            findings, AuditSource.resolve(cache_dir), tmp_path / "audit"
        )

        rapport = (sortie / REPORT_NAME).read_text(encoding="utf-8")
        assert "`vide`" in rapport
        assert "Aucun cas relevé." in rapport

    def test_cas_non_detailles_nommes(self, cache_dir: Path, tmp_path: Path) -> None:
        """Un effectif seul ne permet pas de trier les faux positifs."""
        findings = AuditFindings(
            phase=PhaseName.GLOSSARY,
            spec_name="glossary",
            observations=(
                Observation(
                    category="large",
                    title="Beaucoup de cas",
                    description="…",
                    count=3,
                    samples=(Sample("a", "vu"),),
                    subjects=("a", "b", "c"),
                ),
            ),
        )

        sortie = write_audit(
            findings, AuditSource.resolve(cache_dir), tmp_path / "audit"
        )

        rapport = (sortie / REPORT_NAME).read_text(encoding="utf-8")
        assert "Autres cas (2)" in rapport
        assert "b, c" in rapport

    def test_spec_manquante_ne_bloque_pas(
        self, cache_dir: Path, tmp_path: Path
    ) -> None:
        findings = AuditFindings(phase=PhaseName.GLOSSARY, spec_name="inexistante")

        sortie = write_audit(
            findings, AuditSource.resolve(cache_dir), tmp_path / "audit"
        )

        assert "Cahier des charges manquant" in (sortie / SPEC_NAME).read_text(
            encoding="utf-8"
        )


class TestCli:
    """Ligne de commande."""

    def test_audit_complet(
        self,
        cache_dir: Path,
        tmp_path: Path,
        write_glossary_chunks: Callable[..., Path],
    ) -> None:
        _ = write_glossary_chunks({"0_a": [terme("john", "john")]})
        sortie = tmp_path / "audit"

        code = main([str(cache_dir), "--out", str(sortie)])

        assert code == 0
        assert (sortie / REPORT_NAME).is_file()

    def test_resume_ecrit_sur_stdout(
        self,
        cache_dir: Path,
        tmp_path: Path,
        write_glossary_chunks: Callable[..., Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Le logger console est réglé sur ERROR : sans `print`, rien ne s'affiche."""
        _ = write_glossary_chunks({"0_a": [terme("john", "john")]})
        sortie = tmp_path / "audit"

        _ = main([str(cache_dir), "--out", str(sortie)])

        affiche = capsys.readouterr().out
        assert str(sortie) in affiche
        assert "catégorie(s) d'écart" in affiche

    def test_cache_inexistant_rend_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main([str(tmp_path / "absent")])

        assert code == 1
        assert "Audit impossible" in capsys.readouterr().err

    def test_phase_sans_store_rend_1(self, cache_dir: Path, tmp_path: Path) -> None:
        code = main([str(cache_dir), "--out", str(tmp_path / "audit")])

        assert code == 1
