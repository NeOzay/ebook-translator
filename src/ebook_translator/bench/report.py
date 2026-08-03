"""
Rendu du run : manifeste, métriques et corpus comparatif anonymisé.

L'arbitre lit `README.md`, `metrics.md` et `compare/` — où les variantes ne
portent que des étiquettes `A`, `B`, `C`. Le lien entre étiquette et paramètres
n'existe que dans `manifest.json`, qu'il n'ouvre qu'après avoir conclu. Sans
cette séparation, la réputation d'un modèle pèserait plus lourd que ce qu'il a
réellement produit.

L'attribution des étiquettes est un mélange déterministe seedé sur le `run_id` :
reproductible d'une régénération à l'autre, mais indépendant de l'ordre de
déclaration comme de l'ordre alphabétique.
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from string import ascii_uppercase

from ebook_translator.bench.collect import Corpus, DocumentSet, TranslationCorpus
from ebook_translator.bench.results import VariantResult
from ebook_translator.bench.runner import BenchRun
from ebook_translator.exporter.helper import slugify
from ebook_translator.logger import get_logger

logger = get_logger(__name__)

MANIFEST_NAME = "manifest.json"
METRICS_NAME = "metrics.md"
README_NAME = "README.md"
COMPARE_DIRNAME = "compare"
VERDICT_NAME = "verdict.md"


@dataclass(frozen=True)
class Anonymization:
    """Correspondance entre étiquettes d'arbitrage et variantes réelles.

    Attributes:
        label_to_variant: `A → identifiant de variante`.
        variant_to_label: Correspondance inverse.
    """

    label_to_variant: Mapping[str, str]
    variant_to_label: Mapping[str, str]

    @property
    def labels(self) -> tuple[str, ...]:
        """Étiquettes dans l'ordre alphabétique."""
        return tuple(sorted(self.label_to_variant))


def anonymize(variant_ids: Sequence[str], run_id: str) -> Anonymization:
    """Attribue une étiquette d'arbitrage à chaque variante.

    Args:
        variant_ids: Variantes à étiqueter.
        run_id: Graine du mélange, pour un résultat reproductible.

    Returns:
        La correspondance dans les deux sens.

    Raises:
        ValueError: S'il y a plus de variantes que de lettres disponibles.
    """
    if len(variant_ids) > len(ascii_uppercase):
        raise ValueError(
            f"{len(variant_ids)} variantes : au-delà de {len(ascii_uppercase)}, "
            f"les étiquettes d'arbitrage sont épuisées."
        )

    melange = list(variant_ids)
    random.Random(run_id).shuffle(melange)

    label_to_variant = {
        ascii_uppercase[position]: variant_id
        for position, variant_id in enumerate(melange)
    }
    return Anonymization(
        label_to_variant=label_to_variant,
        variant_to_label={v: k for k, v in label_to_variant.items()},
    )


def render_manifest(run: BenchRun, anonymization: Anonymization) -> str:
    """Produit le manifeste JSON, seul document liant étiquettes et paramètres.

    Args:
        run: Run rendu.
        anonymization: Correspondance étiquette ↔ variante.

    Returns:
        Le JSON du manifeste.
    """
    variantes: list[dict[str, object]] = []
    for label in anonymization.labels:
        variant_id = anonymization.label_to_variant[label]
        variant = run.suite.variant(variant_id)
        result = next(
            (r for r in run.variants if r.variant_id == variant_id),
            VariantResult(variant_id=variant_id, status="error", error="non exécutée"),
        )
        variantes.append(
            {
                "label": label,
                "variant_id": variant_id,
                "params": dict(variant.params),
                "status": result.status,
                "seeded_phases": list(result.seeded_phases),
            }
        )

    manifest = {
        "run_id": run.run_id,
        "epub": str(run.suite.epub),
        "language": run.suite.language,
        "config": str(run.config_path),
        "shared_phases": [str(phase) for phase in run.suite.shared_phases],
        "variants": variantes,
    }
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def render_metrics(run: BenchRun, anonymization: Anonymization) -> str:
    """Produit la table des métriques, étiquetée A/B/C.

    Args:
        run: Run rendu.
        anonymization: Correspondance étiquette ↔ variante.

    Returns:
        Le Markdown des métriques.
    """
    par_variante = {r.variant_id: r for r in run.variants}

    lignes: list[str] = [
        f"# Métriques — run {run.run_id}",
        "",
        "Coût et robustesse de chaque variante. Les étiquettes sont anonymes :",
        "les paramètres correspondants ne sont pas dans ce fichier.",
        "",
        "## Totaux par variante",
        "",
        "| Variante | Statut | Durée | Appels LLM | Tokens in | Tokens out | Chunks rejetés |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    for label in anonymization.labels:
        result = par_variante.get(anonymization.label_to_variant[label])
        if result is None:
            lignes.append(f"| {label} | non exécutée | — | — | — | — | — |")
            continue
        rejets = sum(phase.chunks_rejected for phase in result.phases)
        usage = result.usage
        lignes.append(
            f"| {label} | {result.status} | {result.duration_seconds:.0f} s | "
            f"{usage.llm_calls} | {usage.prompt_tokens} | {usage.completion_tokens} | "
            f"{rejets} |"
        )

    lignes += ["", "## Détail par phase", ""]
    lignes.append(
        "| Variante | Phase | Chunks | Cache | Traduits | Rejetés | Appels LLM | "
        "Tokens in | Tokens out | Durée |"
    )
    lignes.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")

    for label in anonymization.labels:
        result = par_variante.get(anonymization.label_to_variant[label])
        if result is None:
            continue
        for phase in result.phases:
            partage = " (partagée)" if phase.name in result.seeded_phases else ""
            lignes.append(
                f"| {label} | {phase.name}{partage} | {phase.chunks_total} | "
                f"{phase.chunks_from_cache} | {phase.chunks_translated} | "
                f"{phase.chunks_rejected} | {phase.usage.llm_calls} | "
                f"{phase.usage.prompt_tokens} | {phase.usage.completion_tokens} | "
                f"{phase.duration_seconds:.0f} s |"
            )

    echecs = [
        (anonymization.variant_to_label[r.variant_id], r)
        for r in run.failed
        if r.variant_id in anonymization.variant_to_label
    ]
    if echecs:
        lignes += ["", "## Variantes en échec", ""]
        for label, result in echecs:
            premiere_ligne = (result.error or "").strip().splitlines()[:1]
            lignes.append(
                f"- **{label}** — {premiere_ligne[0] if premiere_ligne else '?'}"
            )

    return "\n".join(lignes) + "\n"


def render_translation(
    corpus: TranslationCorpus,
    anonymization: Anonymization,
    file_name: str,
) -> str:
    """Produit la comparaison fragment à fragment d'un fichier HTML.

    Args:
        corpus: Corpus de traduction complet.
        anonymization: Correspondance étiquette ↔ variante.
        file_name: Fichier dont on rend les fragments.

    Returns:
        Le Markdown comparatif.
    """
    lignes: list[str] = [f"# Traduction — `{file_name}`", ""]

    for fragment in corpus.fragments:
        if fragment.file != file_name:
            continue
        lignes += [f"## Fragment {fragment.index}", "", "**Source**", ""]
        lignes += _quote(fragment.source)
        for label in anonymization.labels:
            variant_id = anonymization.label_to_variant[label]
            texte = fragment.translations.get(variant_id)
            lignes += ["", f"**{label}**", ""]
            lignes += _quote(texte) if texte is not None else ["> _(non traduit)_"]
        lignes.append("")

    return "\n".join(lignes) + "\n"


def render_documents(
    documents: Sequence[DocumentSet],
    anonymization: Anonymization,
    titre: str,
) -> str:
    """Produit la comparaison de documents Markdown de revue.

    Args:
        documents: Documents à confronter (glossaires, fiches d'analyse).
        anonymization: Correspondance étiquette ↔ variante.
        titre: Titre du document produit.

    Returns:
        Le Markdown comparatif.
    """
    lignes: list[str] = [f"# {titre}", ""]

    for document in documents:
        lignes += [f"## {document.label}", ""]
        for label in anonymization.labels:
            variant_id = anonymization.label_to_variant[label]
            contenu = document.contents.get(variant_id)
            lignes += [f"### {label}", ""]
            if contenu is None:
                lignes += ["_(non produit par cette variante)_", ""]
                continue
            # Les exports de phase portent leurs propres titres H1/H2 : les
            # décaler évite qu'ils remontent au-dessus des sections d'arbitrage.
            lignes += [_demote_headings(contenu).rstrip(), ""]

    return "\n".join(lignes) + "\n"


def render_readme(run: BenchRun, corpus: Corpus, anonymization: Anonymization) -> str:
    """Produit le mode d'emploi remis à l'arbitre.

    Args:
        run: Run rendu.
        corpus: Corpus collecté.
        anonymization: Correspondance étiquette ↔ variante.

    Returns:
        Le Markdown du README.
    """
    lignes: list[str] = [
        f"# Banc d'essais — run {run.run_id}",
        "",
        f"{len(anonymization.labels)} variante(s) comparée(s) sur "
        f"`{run.suite.epub.name}`, étiquetées {', '.join(anonymization.labels)}.",
        "",
        "## Protocole",
        "",
        f"1. Lire `{METRICS_NAME}` — coût et robustesse.",
        f"2. Lire les fichiers de `{COMPARE_DIRNAME}/` — production de chaque variante.",
        f"3. Écrire `{VERDICT_NAME}` : classement argumenté, extraits à l'appui.",
        f"4. **Seulement ensuite**, lire `{MANIFEST_NAME}` et ajouter la levée",
        "   d'anonymat en fin de verdict.",
        "",
        f"`{MANIFEST_NAME}` associe chaque étiquette à son modèle et à ses paramètres.",
        "L'ouvrir avant d'avoir conclu fausse l'arbitrage : c'est toute la raison",
        "d'être de l'anonymisation.",
        "",
        "## Contenu",
        "",
    ]

    if run.suite.shared_phases:
        partagees = ", ".join(f"`{phase}`" for phase in run.suite.shared_phases)
        lignes += [
            f"Phase(s) **partagée(s)** entre toutes les variantes : {partagees}. "
            "Servies depuis un cache commun, elles sont identiques d'une variante à "
            "l'autre — ne pas les compter dans la comparaison.",
            "",
        ]

    if corpus.translation is not None:
        stats = corpus.translation
        lignes += [
            f"- `{COMPARE_DIRNAME}/translation/` — {len(stats.fragments)} fragment(s) "
            f"retenu(s) sur {stats.total}. Les fragments rendus à l'identique par "
            f"toutes les variantes ({stats.identical}) sont écartés.",
        ]
        manquants = {vid: n for vid, n in stats.missing.items() if n}
        if manquants:
            details = ", ".join(
                f"{anonymization.variant_to_label.get(vid, vid)} : {n}"
                for vid, n in manquants.items()
            )
            lignes.append(
                f"  Fragments non produits (traduction manquante) — {details}."
            )
    if corpus.glossary:
        lignes.append(
            f"- `{COMPARE_DIRNAME}/glossary.md` — {len(corpus.glossary)} glossaire(s) "
            f"de revue."
        )
    if corpus.analysis:
        lignes.append(
            f"- `{COMPARE_DIRNAME}/analysis.md` — {len(corpus.analysis)} fiche(s) "
            f"d'analyse littéraire."
        )

    lignes += [
        "",
        "## Critères d'arbitrage",
        "",
        "- **Fidélité** — rien d'ajouté, rien d'omis, sens préservé.",
        "- **Fluidité** — la phrase se lit comme écrite dans la langue cible.",
        "- **Cohérence terminologique** — un même terme source rendu de la même façon.",
        "- **Registre et style** — ton, niveau de langue et voix narrative tenus.",
        "- **Artefacts** — fragments manquants, séparateur `</>` non préservé,",
        "  texte resté en langue source, balises ou marqueurs fuités.",
        "",
        "Arbitrer enfin qualité contre coût : un gain marginal payé au double de",
        "tokens n'est pas forcément le bon choix.",
        "",
    ]
    return "\n".join(lignes) + "\n"


def write_report(run: BenchRun, corpus: Corpus) -> Path:
    """Écrit l'ensemble des documents du run.

    Args:
        run: Run à rendre.
        corpus: Corpus collecté pour ce run.

    Returns:
        Le répertoire du run.
    """
    anonymization = anonymize(corpus.variant_ids, run.run_id)

    (run.root / MANIFEST_NAME).write_text(
        render_manifest(run, anonymization), encoding="utf-8"
    )
    (run.root / METRICS_NAME).write_text(
        render_metrics(run, anonymization), encoding="utf-8"
    )

    compare = run.root / COMPARE_DIRNAME
    compare.mkdir(parents=True, exist_ok=True)

    if corpus.translation is not None and corpus.translation.fragments:
        translation_dir = compare / "translation"
        translation_dir.mkdir(parents=True, exist_ok=True)
        for position, file_name in enumerate(_files(corpus.translation), start=1):
            cible = (
                translation_dir / f"{position:02d}-{slugify(Path(file_name).stem)}.md"
            )
            cible.write_text(
                render_translation(corpus.translation, anonymization, file_name),
                encoding="utf-8",
            )

    if corpus.glossary:
        (compare / "glossary.md").write_text(
            render_documents(corpus.glossary, anonymization, "Glossaire"),
            encoding="utf-8",
        )

    if corpus.analysis:
        (compare / "analysis.md").write_text(
            render_documents(corpus.analysis, anonymization, "Analyse littéraire"),
            encoding="utf-8",
        )

    (run.root / README_NAME).write_text(
        render_readme(run, corpus, anonymization), encoding="utf-8"
    )

    logger.info(f"📝 Rapport écrit : {run.root}")
    return run.root


def _files(corpus: TranslationCorpus) -> list[str]:
    """Fichiers HTML représentés dans le corpus, dans l'ordre d'apparition."""
    vus: list[str] = []
    for fragment in corpus.fragments:
        if fragment.file not in vus:
            vus.append(fragment.file)
    return vus


def _quote(texte: str) -> list[str]:
    """Rend un texte en blockquote Markdown, ligne par ligne."""
    return [f"> {ligne}" if ligne else ">" for ligne in texte.splitlines() or [""]]


def _demote_headings(markdown: str) -> str:
    """Décale les titres Markdown de deux niveaux.

    Args:
        markdown: Document dont les titres commencent en H1.

    Returns:
        Le même document, titres décalés sous les sections d'arbitrage.
    """
    lignes = [
        f"##{ligne}" if ligne.startswith("#") else ligne
        for ligne in markdown.splitlines()
    ]
    return "\n".join(lignes)
