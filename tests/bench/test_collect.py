"""Tests de l'extraction du corpus comparatif (`bench/collect.py`)."""

import os
from pathlib import Path

import pytest

from ebook_translator.bench.collect import (
    collect_corpus,
    collect_documents,
    collect_translation,
    read_source_fragments,
    read_translations,
    variant_caches,
)
from ebook_translator.bench.suite import CorpusOptions
from ebook_translator.pipeline.base import PhaseBase, PhaseName
from ebook_translator.stores.store import Store

SOURCE_EPUB = Path(
    os.environ.get("TEST_EPUB", "tests/Saint-Exupery-Le_Petit_Prince.epub")
)


@pytest.fixture(scope="module")
def sources() -> dict[str, list[tuple[str, str]]]:
    """Fragments source du livre de test, relus une seule fois."""
    return read_source_fragments(SOURCE_EPUB)


@pytest.fixture(scope="module")
def premier_fichier(sources: dict[str, list[tuple[str, str]]]) -> str:
    """Premier fichier HTML du spine portant au moins deux fragments."""
    for nom, fragments in sources.items():
        if len(fragments) >= 2:
            return nom
    raise AssertionError("Le livre de test ne contient pas de fichier exploitable.")


@pytest.fixture(scope="module")
def index(sources: dict[str, list[tuple[str, str]]], premier_fichier: str) -> list[str]:
    """Deux index de fragment réels du premier fichier.

    Les index sont attribués par `HtmlPage.dump()` et ne commencent pas
    forcément à `0` : les prendre du livre plutôt que les supposer.
    """
    return [idx for idx, _ in sources[premier_fichier][:2]]


def ecrire_traductions(
    cache: Path,
    phase: PhaseName,
    file_name: str,
    textes: dict[str, str],
    legacy: bool = False,
) -> None:
    """Peuple le store d'une phase comme l'aurait fait un run.

    Args:
        cache: Cache de la variante.
        phase: Phase dont on peuple le store.
        file_name: Fichier HTML source.
        textes: Traductions à écrire.
        legacy: Écrire à la racine du dossier de phase (ancien `Store`) plutôt
            que dans le sous-dossier `_v2` du `FileByteStore`, qu'emploie un
            run réel.
    """
    store_dir = cache / str(phase)
    if not legacy:
        store_dir = store_dir / PhaseBase.BYTE_STORE_SUBDIR
    Store(store_dir).save_all(file_name, textes)


class TestReadSourceFragments:
    def test_indexe_les_fragments_par_fichier(
        self, sources: dict[str, list[tuple[str, str]]]
    ):
        assert sources
        for fragments in sources.values():
            for index, texte in fragments:
                assert index.isdigit()
                assert isinstance(texte, str)

    def test_deterministe(self, sources: dict[str, list[tuple[str, str]]]):
        assert read_source_fragments(SOURCE_EPUB) == sources


class TestReadTranslations:
    def test_phase_tardive_ecrase_la_precedente(self, tmp_path: Path):
        cache = tmp_path / "cache"
        ecrire_traductions(
            cache, PhaseName.INITIAL, "ch1.xhtml", {"0": "brut", "1": "a"}
        )
        ecrire_traductions(cache, PhaseName.REFINEMENT, "ch1.xhtml", {"0": "affiné"})

        assert read_translations(cache, "ch1.xhtml") == {"0": "affiné", "1": "a"}

    def test_cache_vide(self, tmp_path: Path):
        assert read_translations(tmp_path / "cache", "ch1.xhtml") == {}

    def test_lit_le_layout_legacy_a_la_racine(self, tmp_path: Path):
        cache = tmp_path / "cache"
        ecrire_traductions(
            cache, PhaseName.INITIAL, "ch1.xhtml", {"0": "ancien"}, legacy=True
        )

        assert read_translations(cache, "ch1.xhtml") == {"0": "ancien"}

    def test_le_store_v2_prime_sur_le_legacy(self, tmp_path: Path):
        cache = tmp_path / "cache"
        ecrire_traductions(
            cache, PhaseName.INITIAL, "ch1.xhtml", {"0": "ancien"}, legacy=True
        )
        ecrire_traductions(cache, PhaseName.INITIAL, "ch1.xhtml", {"0": "récent"})

        assert read_translations(cache, "ch1.xhtml") == {"0": "récent"}


class TestCollectTranslation:
    def _caches(
        self, tmp_path: Path, premier_fichier: str, a: dict[str, str], b: dict[str, str]
    ) -> dict[str, Path]:
        caches = {"a": tmp_path / "a" / "cache", "b": tmp_path / "b" / "cache"}
        ecrire_traductions(caches["a"], PhaseName.INITIAL, premier_fichier, a)
        ecrire_traductions(caches["b"], PhaseName.INITIAL, premier_fichier, b)
        return caches

    def test_aligne_source_et_variantes(
        self, tmp_path: Path, premier_fichier: str, index: list[str]
    ):
        caches = self._caches(
            tmp_path,
            premier_fichier,
            {index[0]: "version A"},
            {index[0]: "version B"},
        )

        corpus = collect_translation(SOURCE_EPUB, caches, CorpusOptions())

        assert len(corpus.fragments) == 1
        fragment = corpus.fragments[0]
        assert fragment.file == premier_fichier
        assert fragment.index == index[0]
        assert fragment.translations == {"a": "version A", "b": "version B"}
        assert fragment.source

    def test_ecarte_les_fragments_identiques(
        self, tmp_path: Path, premier_fichier: str, index: list[str]
    ):
        caches = self._caches(
            tmp_path,
            premier_fichier,
            {index[0]: "pareil", index[1]: "A"},
            {index[0]: "pareil", index[1]: "B"},
        )

        corpus = collect_translation(SOURCE_EPUB, caches, CorpusOptions())

        assert [f.index for f in corpus.fragments] == [index[1]]
        assert corpus.identical == 1

    def test_conserve_les_identiques_sur_demande(
        self, tmp_path: Path, premier_fichier: str, index: list[str]
    ):
        caches = self._caches(
            tmp_path, premier_fichier, {index[0]: "pareil"}, {index[0]: "pareil"}
        )

        corpus = collect_translation(
            SOURCE_EPUB, caches, CorpusOptions(include_identical=True)
        )

        assert [f.index for f in corpus.fragments] == [index[0]]
        assert corpus.identical == 1

    def test_compte_les_fragments_manquants(
        self, tmp_path: Path, premier_fichier: str, index: list[str]
    ):
        caches = self._caches(
            tmp_path,
            premier_fichier,
            {index[0]: "A", index[1]: "A"},
            {index[0]: "B"},
        )

        corpus = collect_translation(SOURCE_EPUB, caches, CorpusOptions())

        # 'b' n'a produit qu'un fragment sur l'ensemble du livre.
        assert corpus.missing["b"] == corpus.total - 1
        assert corpus.missing["a"] == corpus.total - 2

    def test_fragment_partiel_reste_dans_le_corpus(
        self, tmp_path: Path, premier_fichier: str, index: list[str]
    ):
        caches = self._caches(
            tmp_path,
            premier_fichier,
            {index[0]: "A", index[1]: "A"},
            {index[0]: "B"},
        )

        corpus = collect_translation(SOURCE_EPUB, caches, CorpusOptions())

        partiel = next(f for f in corpus.fragments if f.index == index[1])
        assert set(partiel.translations) == {"a"}

    def test_plafond_par_fichier(
        self, tmp_path: Path, premier_fichier: str, index: list[str]
    ):
        caches = self._caches(
            tmp_path,
            premier_fichier,
            {index[0]: "A0", index[1]: "A1"},
            {index[0]: "B0", index[1]: "B1"},
        )

        corpus = collect_translation(
            SOURCE_EPUB, caches, CorpusOptions(max_fragments=1)
        )

        assert len(corpus.fragments) == 1
        assert corpus.truncated == 1


class TestCollectDocuments:
    def test_regroupe_par_document(self, tmp_path: Path):
        caches = {"a": tmp_path / "a", "b": tmp_path / "b"}
        for variant_id, cache in caches.items():
            store = cache / str(PhaseName.GLOSSARY)
            store.mkdir(parents=True)
            (store / "chunk 0.md").write_text(f"# {variant_id}", encoding="utf-8")

        documents = collect_documents(caches, PhaseName.GLOSSARY)

        assert [d.label for d in documents] == ["chunk 0"]
        assert documents[0].contents == {"a": "# a", "b": "# b"}

    def test_document_produit_par_une_seule_variante(self, tmp_path: Path):
        caches = {"a": tmp_path / "a", "b": tmp_path / "b"}
        store = caches["a"] / str(PhaseName.LITERARY_ANALYSIS)
        store.mkdir(parents=True)
        (store / "bloc-1.md").write_text("fiche", encoding="utf-8")

        documents = collect_documents(caches, PhaseName.LITERARY_ANALYSIS)

        assert documents[0].contents == {"a": "fiche"}

    def test_phase_absente(self, tmp_path: Path):
        caches = {"a": tmp_path / "a"}

        assert collect_documents(caches, PhaseName.GLOSSARY) == ()


class TestCollectCorpus:
    def test_sections_desactivees(
        self, tmp_path: Path, premier_fichier: str, index: list[str]
    ):
        caches = variant_caches(tmp_path, ["a", "b"])
        for cache in caches.values():
            ecrire_traductions(
                cache, PhaseName.INITIAL, premier_fichier, {index[0]: "x"}
            )

        corpus = collect_corpus(
            SOURCE_EPUB,
            caches,
            CorpusOptions(translation=False, glossary=False, analysis=False),
        )

        assert corpus.translation is None
        assert corpus.glossary == ()
        assert corpus.analysis == ()
        assert corpus.variant_ids == ("a", "b")


class TestVariantCaches:
    def test_chemins_de_cache(self, tmp_path: Path):
        caches = variant_caches(tmp_path, ["a", "b"])

        assert caches == {
            "a": tmp_path / "a" / "cache",
            "b": tmp_path / "b" / "cache",
        }
