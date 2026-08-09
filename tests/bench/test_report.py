"""Tests du rendu du rapport (`bench/report.py`)."""

import json
from pathlib import Path

import pytest

from ebook_translator.bench.collect import (
    Corpus,
    DocumentSet,
    Fragment,
    TranslationCorpus,
)
from ebook_translator.bench.report import (
    COMPARE_DIRNAME,
    MANIFEST_NAME,
    METRICS_NAME,
    README_NAME,
    anonymize,
    render_documents,
    render_manifest,
    render_metrics,
    render_readme,
    render_translation,
    write_report,
)
from ebook_translator.bench.results import PhaseResult, VariantResult
from ebook_translator.bench.runner import BenchRun
from ebook_translator.bench.suite import BenchSuite, RunEnv, Seed, Variant
from ebook_translator.llm.usage import PhaseUsage
from ebook_translator.pipeline.base import PhaseName
from ebook_translator.pipeline.builder import PipelineBuilder

RUN_ID = "20260802_143005"


def build_stub(env: RunEnv) -> PipelineBuilder:
    return PipelineBuilder()


@pytest.fixture
def epub(tmp_path: Path) -> Path:
    source = tmp_path / "Mon Livre.epub"
    source.write_bytes(b"PK\x03\x04")
    return source


@pytest.fixture
def run(tmp_path: Path, epub: Path) -> BenchRun:
    suite = BenchSuite(
        epub=epub,
        variants=[
            Variant("rapide", {"model": "flash", "temperature": 0.5}, build_stub),
            Variant("lent", {"model": "reasoner", "temperature": 1.0}, build_stub),
        ],
        seed=Seed(build=build_stub, phases=(PhaseName.LITERARY_ANALYSIS,)),
        language="Francais",
    )
    phase = PhaseResult(
        name="initial",
        chunks_total=6,
        chunks_translated=6,
        chunks_rejected=1,
        duration_seconds=30.0,
        usage=PhaseUsage(6, 5000, 2000, 0, 0),
    )
    partagee = PhaseResult(
        name="literary analysis",
        chunks_total=2,
        chunks_from_cache=2,
        usage=PhaseUsage(),
    )
    root = tmp_path / "runs" / RUN_ID
    root.mkdir(parents=True)
    return BenchRun(
        run_id=RUN_ID,
        root=root,
        suite=suite,
        config_path=tmp_path / "config.py",
        seed=VariantResult(variant_id="seed", status="ok"),
        variants=(
            VariantResult(
                variant_id="rapide",
                phases=(partagee, phase),
                duration_seconds=40.0,
                seeded_phases=("literary analysis",),
            ),
            VariantResult(
                variant_id="lent",
                phases=(partagee, phase),
                duration_seconds=90.0,
                seeded_phases=("literary analysis",),
            ),
        ),
    )


@pytest.fixture
def corpus() -> Corpus:
    return Corpus(
        variant_ids=("rapide", "lent"),
        translation=TranslationCorpus(
            fragments=(
                Fragment(
                    file="OEBPS/ch1.xhtml",
                    index="1",
                    source="The wallpaper.",
                    translations={
                        "rapide": "Le papier peint.",
                        "lent": "La tapisserie.",
                    },
                ),
                Fragment(
                    file="OEBPS/ch1.xhtml",
                    index="2",
                    source="It creeps.",
                    translations={"rapide": "Il rampe."},
                ),
            ),
            total=10,
            identical=3,
            truncated=0,
            missing={"rapide": 0, "lent": 1},
        ),
        glossary=(
            DocumentSet(
                label="chunk 0",
                contents={"rapide": "# Glossaire\n\n| a |", "lent": "# Glossaire\n"},
            ),
        ),
        analysis=(DocumentSet(label="bloc-1", contents={"rapide": "# Fiche"}),),
    )


class TestAnonymize:
    def test_etiquettes_attribuees_a_toutes_les_variantes(self):
        anonymization = anonymize(["a", "b", "c"], RUN_ID)

        assert anonymization.labels == ("A", "B", "C")
        assert set(anonymization.label_to_variant.values()) == {"a", "b", "c"}

    def test_deterministe_sur_le_run_id(self):
        premier = anonymize(["a", "b", "c"], RUN_ID)
        second = anonymize(["a", "b", "c"], RUN_ID)

        assert premier.label_to_variant == second.label_to_variant

    def test_run_id_different_change_l_attribution(self):
        # Sinon l'ordre de déclaration serait un indice exploitable.
        attributions = {
            tuple(anonymize(["a", "b", "c", "d"], str(seed)).label_to_variant.values())
            for seed in range(20)
        }

        assert len(attributions) > 1

    def test_correspondance_inverse(self):
        anonymization = anonymize(["a", "b"], RUN_ID)

        for label, variant_id in anonymization.label_to_variant.items():
            assert anonymization.variant_to_label[variant_id] == label

    def test_trop_de_variantes(self):
        with pytest.raises(ValueError, match="épuisées"):
            _ = anonymize([f"v{n}" for n in range(27)], RUN_ID)


class TestRenderManifest:
    def test_relie_etiquette_et_parametres(self, run: BenchRun):
        anonymization = anonymize(["rapide", "lent"], RUN_ID)

        manifest = json.loads(render_manifest(run, anonymization))

        assert manifest["run_id"] == RUN_ID
        assert manifest["shared_phases"] == ["literary analysis"]
        par_label = {v["label"]: v for v in manifest["variants"]}
        etiquette = anonymization.variant_to_label["rapide"]
        assert par_label[etiquette]["params"] == {
            "model": "flash",
            "temperature": 0.5,
        }


class TestRenderMetrics:
    def test_n_expose_aucun_parametre(self, run: BenchRun):
        anonymization = anonymize(["rapide", "lent"], RUN_ID)

        metrics = render_metrics(run, anonymization)

        assert "flash" not in metrics
        assert "reasoner" not in metrics
        assert "temperature" not in metrics
        assert "rapide" not in metrics

    def test_totaux_et_detail_par_phase(self, run: BenchRun):
        anonymization = anonymize(["rapide", "lent"], RUN_ID)

        metrics = render_metrics(run, anonymization)

        assert "## Totaux par variante" in metrics
        assert "## Détail par phase" in metrics
        assert "literary analysis (partagée)" in metrics

    def test_signale_les_echecs(self, run: BenchRun):
        echec = VariantResult(
            variant_id="lent", status="error", error="RuntimeError: boum\ntrace"
        )
        run = BenchRun(
            run_id=run.run_id,
            root=run.root,
            suite=run.suite,
            config_path=run.config_path,
            seed=run.seed,
            variants=(run.variants[0], echec),
        )
        anonymization = anonymize(["rapide", "lent"], RUN_ID)

        metrics = render_metrics(run, anonymization)

        assert "## Variantes en échec" in metrics
        assert "RuntimeError: boum" in metrics

    def test_statut_degrade_porte_son_ratio(self, run: BenchRun):
        degradee = VariantResult(
            variant_id="lent",
            status="partial",
            phases=(PhaseResult(name="initial", chunks_total=4, chunks_processed=1),),
        )
        run = BenchRun(
            run_id=run.run_id,
            root=run.root,
            suite=run.suite,
            config_path=run.config_path,
            seed=run.seed,
            variants=(run.variants[0], degradee),
        )
        anonymization = anonymize(["rapide", "lent"], RUN_ID)

        metrics = render_metrics(run, anonymization)

        # Sans le ratio, il faudrait rouvrir `result.json` pour savoir si la
        # variante a produit quelque chose d'exploitable.
        assert "partial (initial: 1/4 chunks)" in metrics


class TestWriteReportListeToutesLesVariantes:
    """Une variante écartée du corpus doit rester visible au rapport.

    Le corpus ne retient que les variantes complètes ; si les étiquettes en
    dérivaient, une variante en échec disparaîtrait de `metrics.md` — l'inverse
    du but recherché. Constaté sur un run réel dégradé le 2026-08-09.
    """

    def test_variante_absente_du_corpus_reste_dans_les_metriques(
        self, run: BenchRun, corpus: Corpus
    ):
        # Corpus ne contenant qu'une des deux variantes du run.
        restreint = Corpus(
            variant_ids=("rapide",),
            translation=None,
            glossary=corpus.glossary,
            analysis=corpus.analysis,
        )

        racine = write_report(run, restreint)

        metrics = (racine / METRICS_NAME).read_text(encoding="utf-8")
        manifest = json.loads((racine / MANIFEST_NAME).read_text(encoding="utf-8"))

        assert len(manifest["variants"]) == 2, "une variante a disparu du manifeste"
        assert metrics.count("\n| ") >= 2


class TestRenderTranslation:
    def test_source_puis_variantes_etiquetees(self, corpus: Corpus):
        assert corpus.translation is not None
        anonymization = anonymize(["rapide", "lent"], RUN_ID)

        rendu = render_translation(corpus.translation, anonymization, "OEBPS/ch1.xhtml")

        assert "## Fragment 1" in rendu
        assert "> The wallpaper." in rendu
        assert "> Le papier peint." in rendu
        for label in anonymization.labels:
            assert f"**{label}**" in rendu
        assert "rapide" not in rendu

    def test_fragment_non_traduit_signale(self, corpus: Corpus):
        assert corpus.translation is not None
        anonymization = anonymize(["rapide", "lent"], RUN_ID)

        rendu = render_translation(corpus.translation, anonymization, "OEBPS/ch1.xhtml")

        assert "_(non traduit)_" in rendu


class TestRenderDocuments:
    def test_decale_les_titres_des_exports(self, corpus: Corpus):
        anonymization = anonymize(["rapide", "lent"], RUN_ID)

        rendu = render_documents(corpus.glossary, anonymization, "Glossaire")

        # Le H1 de l'export ne doit pas concurrencer le titre du document.
        assert "### Glossaire" in rendu
        assert "\n# Glossaire\n" not in rendu

    def test_document_absent_signale(self, corpus: Corpus):
        anonymization = anonymize(["rapide", "lent"], RUN_ID)

        rendu = render_documents(corpus.analysis, anonymization, "Analyse")

        assert "_(non produit par cette variante)_" in rendu


class TestRenderReadme:
    def test_rappelle_le_protocole_et_l_aveugle(self, run: BenchRun, corpus: Corpus):
        anonymization = anonymize(["rapide", "lent"], RUN_ID)

        readme = render_readme(run, corpus, anonymization)

        assert MANIFEST_NAME in readme
        assert "Seulement ensuite" in readme
        assert "literary analysis" in readme
        assert "Fidélité" in readme

    def test_signale_les_fragments_manquants(self, run: BenchRun, corpus: Corpus):
        anonymization = anonymize(["rapide", "lent"], RUN_ID)

        readme = render_readme(run, corpus, anonymization)

        etiquette = anonymization.variant_to_label["lent"]
        assert f"{etiquette} : 1" in readme


class TestWriteReport:
    def test_ecrit_tous_les_documents(self, run: BenchRun, corpus: Corpus):
        racine = write_report(run, corpus)

        assert (racine / MANIFEST_NAME).exists()
        assert (racine / METRICS_NAME).exists()
        assert (racine / README_NAME).exists()
        assert (racine / COMPARE_DIRNAME / "glossary.md").exists()
        assert (racine / COMPARE_DIRNAME / "analysis.md").exists()
        traductions = list((racine / COMPARE_DIRNAME / "translation").glob("*.md"))
        assert len(traductions) == 1

    def test_sections_vides_non_ecrites(self, run: BenchRun):
        vide = Corpus(variant_ids=("rapide", "lent"))

        racine = write_report(run, vide)

        assert not (racine / COMPARE_DIRNAME / "glossary.md").exists()
        assert not (racine / COMPARE_DIRNAME / "translation").exists()
