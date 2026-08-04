"""Métriques et catalogue d'erreurs de la phase glossaire."""

from collections.abc import Callable
from pathlib import Path

import pytest

from ebook_translator.audit.findings import AuditFindings, Observation
from ebook_translator.audit.glossary_auditor import GlossaryAuditor
from ebook_translator.audit.source import AuditSource
from ebook_translator.glossary import converged_weight
from ebook_translator.pipeline.base import PhaseBase, PhaseName

from .conftest import terme

SOURCE = (
    "John came back from the village. The cellar was dark, and John hated it.\n"
    "Jennie watched John cross the garden. Jennie said nothing at all.\n"
    "Later John and Jennie walked to the garden again, past the village fountain.\n"
)


def _source_avec_texte(cache_dir: Path, texte: str = SOURCE) -> AuditSource:
    """Source dont le texte est injecté sans passer par un EPUB.

    `source_fragments` est un `cached_property` : préremplir le cache d'instance
    évite de fabriquer un EPUB pour chaque test.

    Args:
        cache_dir: Cache à auditer.
        texte: Texte source à simuler.

    Returns:
        La source prête à auditer.
    """
    source = AuditSource.resolve(cache_dir)
    source.__dict__["source_fragments"] = tuple(texte.splitlines())
    return source


def _observation(findings: AuditFindings, category: str) -> Observation | None:
    """Retrouve une observation par catégorie.

    Args:
        findings: Constats de l'auditeur.
        category: Catégorie recherchée.

    Returns:
        L'observation, ou `None` si la catégorie n'a rien relevé.
    """
    return next((o for o in findings.observations if o.category == category), None)


def _count(findings: AuditFindings, category: str) -> int:
    """Effectif d'une catégorie.

    Une catégorie mesurée mais sans cas figure au catalogue avec un effectif nul ;
    seule une catégorie non mesurable en est absente.

    Args:
        findings: Constats de l'auditeur.
        category: Catégorie recherchée.

    Returns:
        L'effectif relevé, `0` si la catégorie n'a rien trouvé ou n'a pas été mesurée.
    """
    observation = _observation(findings, category)
    return observation.count if observation else 0


def _metric(findings: AuditFindings, label: str) -> float | int:
    """Valeur d'une métrique par libellé.

    Args:
        findings: Constats de l'auditeur.
        label: Libellé recherché.

    Returns:
        La valeur mesurée.
    """
    return next(m.value for m in findings.metrics if m.label == label)


@pytest.fixture
def auditer(
    cache_dir: Path, write_glossary_chunks: Callable[..., Path]
) -> Callable[..., AuditFindings]:
    """Écrit des chunks puis les audite."""

    def _auditer(chunks: dict[str, list[dict[str, str]]]) -> AuditFindings:
        _ = write_glossary_chunks(chunks)
        return GlossaryAuditor().run(_source_avec_texte(cache_dir))

    return _auditer


class TestMetriques:
    """Chiffres mesurés."""

    def test_compte_chunks_lignes_et_termes_uniques(
        self, auditer: Callable[..., AuditFindings]
    ) -> None:
        findings = auditer(
            {
                "0_a": [terme("john", "john"), terme("jennie", "jennie")],
                "1_b": [terme("john", "john")],
            }
        )

        assert _metric(findings, "Chunks glossaire") == 2
        assert _metric(findings, "Lignes émises") == 3
        assert _metric(findings, "Termes uniques") == 2
        assert _metric(findings, "Réémissions") == 1

    def test_densite_rapportee_pour_mille_mots(
        self, auditer: Callable[..., AuditFindings]
    ) -> None:
        findings = auditer({"0_a": [terme("john", "john")]})

        mots = _metric(findings, "Mots dans la source")
        assert mots > 0
        assert _metric(findings, "Densité") == pytest.approx(1 / mots * 1000)

    def test_union_ne_compte_pas_deux_fois_le_meme_terme(
        self, auditer: Callable[..., AuditFindings]
    ) -> None:
        """`the fountain` tombe dans trois catégories : l'union en compte un."""
        findings = auditer({"0_a": [terme("the fountain", "la fontaine")]})

        assert _metric(findings, "Termes touchés par au moins une observation") == 1
        assert sum(o.count for o in findings.observations if o.counts_terms) > 1, (
            "sans quoi le test ne prouve rien"
        )

    def test_candidats_manques_exclus_de_l_union(
        self, auditer: Callable[..., AuditFindings]
    ) -> None:
        """`candidat-manque` désigne des mots absents du glossaire, pas des termes."""
        findings = auditer({"0_a": [terme("jennie", "jennie", type_="personnage")]})

        manques = _observation(findings, "candidat-manque")
        assert manques is not None and manques.count > 0
        touches = findings.affected_subjects()
        assert all(sujet not in touches for sujet in manques.subjects)

    def test_livre_trop_court_signale_en_limite(
        self, auditer: Callable[..., AuditFindings]
    ) -> None:
        """Sous le poids de convergence, la réémission est prescrite, pas fautive."""
        findings = auditer({"0_a": [terme("john", "john")]})

        assert any("trop court pour la convergence" in n for n in findings.notes)
        assert _metric(findings, "Poids de convergence") == converged_weight()
        assert _metric(findings, "Termes convergés") == 0

    def test_composition_par_type(self, auditer: Callable[..., AuditFindings]) -> None:
        findings = auditer(
            {
                "0_a": [
                    terme("john", "john", type_="personnage"),
                    terme("the garden", "le jardin", type_="lieu"),
                ]
            }
        )

        assert _metric(findings, "Type « personnage »") == 1
        assert _metric(findings, "Type « lieu »") == 1


class TestCatalogueErreurs:
    """Écarts relevés."""

    def test_traduction_divergente_signalee(
        self, auditer: Callable[..., AuditFindings]
    ) -> None:
        findings = auditer(
            {
                "0_a": [terme("the garden", "le jardin")],
                "1_b": [terme("the garden", "le potager")],
            }
        )

        observation = _observation(findings, "traduction-instable")
        assert observation is not None
        assert observation.count == 1
        assert observation.samples[0].subject == "the garden"

    def test_traduction_stable_non_signalee(
        self, auditer: Callable[..., AuditFindings]
    ) -> None:
        findings = auditer(
            {
                "0_a": [terme("the garden", "le jardin")],
                "1_b": [terme("the garden", "le jardin")],
            }
        )

        assert _count(findings, "traduction-instable") == 0

    def test_classement_contradictoire_signale(
        self, auditer: Callable[..., AuditFindings]
    ) -> None:
        findings = auditer(
            {
                "0_a": [terme("john", "john", type_="personnage", sexe="m")],
                "1_b": [terme("john", "john", type_="personnage", sexe="f")],
            }
        )

        observation = _observation(findings, "classement-instable")
        assert observation is not None
        assert observation.count == 1

    def test_reemission_avant_convergence_non_signalee(
        self, auditer: Callable[..., AuditFindings]
    ) -> None:
        """Le prompt réclame la réémission tant que le terme n'est pas stabilisé."""
        findings = auditer(
            {
                "0_a": [terme("john", "john")],
                "1_b": [terme("john", "john")],
                "2_c": [terme("john", "john")],
            }
        )

        assert _count(findings, "redondance") == 0

    def test_reemission_apres_convergence_signalee(
        self, auditer: Callable[..., AuditFindings]
    ) -> None:
        """Passé le poids de convergence, le terme est listé « NE PAS inclure »."""
        chunks = {
            f"{index}_x": [terme("john", "john")]
            for index in range(converged_weight() + 1)
        }

        findings = auditer(chunks)

        observation = _observation(findings, "redondance")
        assert observation is not None
        assert observation.count == 1
        assert observation.samples[0].subject == "john"
        assert "1 réémission(s)" in observation.samples[0].evidence

    def test_chunks_ordonnes_par_index_numerique(
        self, auditer: Callable[..., AuditFindings]
    ) -> None:
        """Un tri lexicographique placerait `10_` avant `2_` et fausserait le cumul."""
        chunks = {
            f"{index}_x": [terme("john", "john")]
            for index in reversed(range(converged_weight() + 1))
        }

        findings = auditer(chunks)

        assert _count(findings, "redondance") == 1

    def test_nom_commun_a_article_signale(
        self, auditer: Callable[..., AuditFindings]
    ) -> None:
        findings = auditer({"0_a": [terme("the cellar", "la cave", type_="lieu")]})

        observation = _observation(findings, "nom-commun-article")
        assert observation is not None
        assert observation.samples[0].subject == "the cellar"

    def test_nom_propre_a_article_non_signale(
        self, cache_dir: Path, write_glossary_chunks: Callable[..., Path]
    ) -> None:
        """`the Thames` porte un article mais reste une entité nommée."""
        _ = write_glossary_chunks(
            {"0_a": [terme("the thames", "la tamise", type_="lieu")]}
        )
        source = _source_avec_texte(
            cache_dir, "They crossed the Thames at dawn, then the Thames again.\n"
        )

        findings = GlossaryAuditor().run(source)

        assert _count(findings, "nom-commun-article") == 0

    def test_terme_non_recurrent_signale(
        self, auditer: Callable[..., AuditFindings]
    ) -> None:
        findings = auditer({"0_a": [terme("the fountain", "la fontaine")]})

        observation = _observation(findings, "ancrage-faible")
        assert observation is not None
        assert observation.samples[0].subject == "the fountain"

    def test_ancrage_compte_le_terme_sans_son_article(
        self, auditer: Callable[..., AuditFindings]
    ) -> None:
        """`the village` n'apparaît jamais tel quel, `village` deux fois."""
        findings = auditer({"0_a": [terme("the village", "le village")]})

        observation = _observation(findings, "ancrage-faible")
        assert observation is None or all(
            s.subject != "the village" for s in observation.samples
        )

    def test_entite_recurrente_absente_signalee(
        self, auditer: Callable[..., AuditFindings]
    ) -> None:
        findings = auditer({"0_a": [terme("jennie", "jennie", type_="personnage")]})

        observation = _observation(findings, "candidat-manque")
        assert observation is not None
        assert any(s.subject == "john" for s in observation.samples)

    def test_pronom_capitalise_non_pris_pour_une_entite(
        self, cache_dir: Path, write_glossary_chunks: Callable[..., Path]
    ) -> None:
        """`I've` est toujours capitalisé : ce n'est pas un nom propre."""
        _ = write_glossary_chunks({"0_a": [terme("john", "john")]})
        source = _source_avec_texte(
            cache_dir,
            "Well I've said it. And I've said it again. I've said it thrice.\n",
        )

        findings = GlossaryAuditor().run(source)

        observation = _observation(findings, "candidat-manque")
        assert observation is None or all(
            "i" not in s.subject for s in observation.samples
        )


class TestSansSource:
    """Comportement quand aucun EPUB n'a pu être résolu."""

    def test_metriques_dependant_du_texte_omises(
        self, cache_dir: Path, write_glossary_chunks: Callable[..., Path]
    ) -> None:
        _ = write_glossary_chunks({"0_a": [terme("the cellar", "la cave")]})

        findings = GlossaryAuditor().run(AuditSource.resolve(cache_dir))

        libelles = {m.label for m in findings.metrics}
        assert "Densité" not in libelles
        assert _observation(findings, "nom-commun-article") is None
        assert any("Aucun EPUB source" in note for note in findings.notes)

    def test_metriques_de_coherence_conservees(
        self, cache_dir: Path, write_glossary_chunks: Callable[..., Path]
    ) -> None:
        """L'instabilité se mesure sans le texte source."""
        _ = write_glossary_chunks(
            {
                "0_a": [terme("the garden", "le jardin")],
                "1_b": [terme("the garden", "le potager")],
            }
        )

        findings = GlossaryAuditor().run(AuditSource.resolve(cache_dir))

        assert _observation(findings, "traduction-instable") is not None


class TestRepliMarkdown:
    """Lecture des tables de revue quand le store v2 manque."""

    def test_table_markdown_relue(self, cache_dir: Path) -> None:
        dossier = cache_dir / str(PhaseName.GLOSSARY)
        dossier.mkdir()
        _ = (dossier / "chunk 0.md").write_text(
            "| Terme | Type | Sexe | Proposition |\n"
            "| --- | --- | --- | --- |\n"
            "| john | personnage | Masculin | **john** |\n",
            encoding="utf-8",
        )

        findings = GlossaryAuditor().run(_source_avec_texte(cache_dir))

        assert _metric(findings, "Termes uniques") == 1

    def test_v2_prioritaire_sur_le_markdown(
        self, cache_dir: Path, write_glossary_chunks: Callable[..., Path]
    ) -> None:
        _ = write_glossary_chunks({"0_a": [terme("john", "john")]})
        dossier = cache_dir / str(PhaseName.GLOSSARY)
        _ = (dossier / "chunk 0.md").write_text(
            "| Terme | Type | Sexe | Proposition |\n"
            "| --- | --- | --- | --- |\n"
            "| jennie | personnage | Féminin | **jennie** |\n"
            "| mary | personnage | Féminin | **mary** |\n",
            encoding="utf-8",
        )

        findings = GlossaryAuditor().run(_source_avec_texte(cache_dir))

        assert _metric(findings, "Termes uniques") == 1


class TestChargeInvalide:
    """Robustesse à un store abîmé."""

    def test_charge_non_json_ignoree(self, cache_dir: Path) -> None:
        import json

        dossier = cache_dir / str(PhaseName.GLOSSARY) / PhaseBase.BYTE_STORE_SUBDIR
        dossier.mkdir(parents=True)
        _ = (dossier / "glossary_x.json").write_text(
            json.dumps({"0_a": "pas du json"}), encoding="utf-8"
        )

        findings = GlossaryAuditor().run(_source_avec_texte(cache_dir))

        assert _metric(findings, "Termes uniques") == 0

    def test_entree_sans_terme_ecartee(self, cache_dir: Path) -> None:
        import json

        dossier = cache_dir / str(PhaseName.GLOSSARY) / PhaseBase.BYTE_STORE_SUBDIR
        dossier.mkdir(parents=True)
        charge = json.dumps([{"type": "objet"}, terme("john", "john")])
        _ = (dossier / "glossary_x.json").write_text(
            json.dumps({"0_a": charge}), encoding="utf-8"
        )

        findings = GlossaryAuditor().run(_source_avec_texte(cache_dir))

        assert _metric(findings, "Termes uniques") == 1
