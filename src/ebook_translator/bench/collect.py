"""
Extraction du corpus comparatif depuis les workspaces des variantes.

Trois matières sont collectées :

- **Traduction** — les stores de phase contiennent `{index de fragment: texte}`
  par fichier HTML. `HtmlPage.dump()` produit les mêmes index sur le livre
  source, ce qui permet d'aligner source et traductions sans rejouer le
  pipeline. Comme à la reconstruction de l'EPUB, les phases tardives écrasent
  les précédentes sur un même index.
- **Glossaire** et **analyse littéraire** — ces phases exportent déjà un
  Markdown de revue dans leur propre store ; il est repris tel quel.

Les fragments traduits à l'identique par toutes les variantes sont écartés par
défaut : ils ne départagent rien et diluent le corpus remis à l'arbitre.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ebooklib import epub

from ebook_translator.bench.suite import CorpusOptions
from ebook_translator.htmlpage import HtmlPage
from ebook_translator.logger import get_logger
from ebook_translator.pipeline.base import PhaseBase, PhaseName
from ebook_translator.stores.store import Store
from ebook_translator.translation.epub_handler import (
    extract_html_items_in_spine_order,
)

logger = get_logger(__name__)

TRANSLATION_PHASES: tuple[PhaseName, ...] = (PhaseName.INITIAL, PhaseName.REFINEMENT)
"""Phases dont le store porte du texte traduit, dans l'ordre d'écrasement."""

CACHE_DIRNAME = "cache"
"""Nom du cache dans le workspace d'une variante (voir `workspace.py`)."""


@dataclass(frozen=True)
class Fragment:
    """Un fragment source et ses traductions, une par variante.

    Attributes:
        file: Fichier HTML d'origine, dans l'ordre du spine.
        index: Index du fragment dans ce fichier.
        source: Texte source.
        translations: Traduction par identifiant de variante. Une variante qui
            n'a pas produit ce fragment est absente du mapping.
    """

    file: str
    index: str
    source: str
    translations: Mapping[str, str]

    def is_identical(self, variant_ids: Sequence[str]) -> bool:
        """Indique si toutes les variantes ont rendu exactement le même texte.

        Args:
            variant_ids: Variantes à confronter.

        Returns:
            True si toutes ont produit ce fragment et avec le même texte.
        """
        textes = {self.translations.get(vid) for vid in variant_ids}
        return len(textes) == 1 and None not in textes


@dataclass(frozen=True)
class TranslationCorpus:
    """Fragments retenus pour la comparaison, et ce qui a été écarté.

    Attributes:
        fragments: Fragments retenus, dans l'ordre du livre.
        total: Fragments traduisibles du livre.
        identical: Fragments rendus à l'identique par toutes les variantes.
        truncated: Fragments écartés par le plafond `max_fragments`.
        missing: Nombre de fragments non produits, par variante.
    """

    fragments: tuple[Fragment, ...]
    total: int
    identical: int
    truncated: int
    missing: Mapping[str, int]


@dataclass(frozen=True)
class DocumentSet:
    """Un même document de revue, rendu par plusieurs variantes.

    Attributes:
        label: Nom du document (nom de fichier sans extension).
        contents: Markdown par identifiant de variante.
    """

    label: str
    contents: Mapping[str, str]


@dataclass(frozen=True)
class Corpus:
    """Matière comparative complète d'un run.

    Attributes:
        variant_ids: Variantes comparées, dans l'ordre de déclaration.
        translation: Corpus de traduction, `None` si non demandé ou vide.
        glossary: Glossaires de revue, un jeu par chunk.
        analysis: Fiches d'analyse littéraire, un jeu par bloc.
    """

    variant_ids: tuple[str, ...]
    translation: TranslationCorpus | None = None
    glossary: tuple[DocumentSet, ...] = ()
    analysis: tuple[DocumentSet, ...] = ()


def read_source_fragments(epub_path: Path) -> dict[str, list[tuple[str, str]]]:
    """Extrait les fragments traduisibles du livre source.

    Args:
        epub_path: EPUB source.

    Returns:
        Mapping `fichier HTML → [(index, texte source)]`, dans l'ordre du spine.
    """
    book = epub.read_epub(epub_path)  # pyright: ignore[reportUnknownMemberType]
    html_items, _ = extract_html_items_in_spine_order(book)

    fragments: dict[str, list[tuple[str, str]]] = {}
    for item in html_items:
        page = HtmlPage(item)
        fragments[str(item.file_name)] = [
            (tag_key.index, texte) for tag_key, texte in page.dump()
        ]
    return fragments


def read_translations(cache_dir: Path, file_name: str) -> dict[str, str]:
    """Traductions d'un fichier HTML, toutes phases confondues.

    Les phases sont fusionnées dans l'ordre de `TRANSLATION_PHASES` : la
    dernière écrase la précédente, comme à la reconstruction de l'EPUB.

    Args:
        cache_dir: Cache de la variante.
        file_name: Fichier HTML source.

    Returns:
        Mapping `index de fragment → texte traduit`.
    """
    fusion: dict[str, str] = {}
    for phase in TRANSLATION_PHASES:
        store_dir = cache_dir / str(phase)
        if not store_dir.is_dir():
            continue
        # Le `Store` legacy écrit à la racine du dossier de phase, le
        # `FileByteStore` v2 dans le sous-dossier `_v2`. Les deux partagent la
        # convention `<clé assainie>_<md5 court>.json`, donc le même `Store` les
        # lit ; le v2 passe en dernier, c'est lui qui fait foi.
        for dossier in (store_dir, store_dir / PhaseBase.BYTE_STORE_SUBDIR):
            if not dossier.is_dir():
                continue
            fusion.update(Store(dossier).get_from_file(file_name, use_fallback=False))
    return fusion


def collect_translation(
    epub_path: Path,
    caches: Mapping[str, Path],
    options: CorpusOptions,
) -> TranslationCorpus:
    """Aligne le texte source et les traductions de chaque variante.

    Args:
        epub_path: EPUB source, commun aux variantes.
        caches: Cache par identifiant de variante, dans l'ordre de comparaison.
        options: Réglages d'extraction (plafond, fragments identiques).

    Returns:
        Le corpus de traduction et ses compteurs.
    """
    variant_ids = list(caches)
    sources = read_source_fragments(epub_path)

    retenus: list[Fragment] = []
    total = 0
    identiques = 0
    tronques = 0
    manquants: dict[str, int] = dict.fromkeys(variant_ids, 0)

    for file_name, fragments_source in sources.items():
        par_variante = {
            vid: read_translations(cache, file_name) for vid, cache in caches.items()
        }
        retenus_fichier = 0

        for index, texte_source in fragments_source:
            total += 1
            traductions = {
                vid: textes[index]
                for vid, textes in par_variante.items()
                if index in textes
            }
            for vid in variant_ids:
                if vid not in traductions:
                    manquants[vid] += 1

            if not traductions:
                continue

            fragment = Fragment(
                file=file_name,
                index=index,
                source=texte_source,
                translations=traductions,
            )

            if fragment.is_identical(variant_ids):
                identiques += 1
                if not options.include_identical:
                    continue

            if (
                options.max_fragments is not None
                and retenus_fichier >= options.max_fragments
            ):
                tronques += 1
                continue

            retenus.append(fragment)
            retenus_fichier += 1

    return TranslationCorpus(
        fragments=tuple(retenus),
        total=total,
        identical=identiques,
        truncated=tronques,
        missing=manquants,
    )


def collect_documents(
    caches: Mapping[str, Path], phase: PhaseName
) -> tuple[DocumentSet, ...]:
    """Regroupe les Markdown de revue d'une phase, document par document.

    Args:
        caches: Cache par identifiant de variante.
        phase: Phase dont on collecte les exports (`glossary`, `literary analysis`).

    Returns:
        Un `DocumentSet` par document, trié par nom. Les documents qu'aucune
        variante n'a produits sont absents.
    """
    par_label: dict[str, dict[str, str]] = {}

    for variant_id, cache in caches.items():
        store_dir = cache / str(phase)
        if not store_dir.is_dir():
            continue
        for markdown in sorted(store_dir.glob("*.md")):
            par_label.setdefault(markdown.stem, {})[variant_id] = markdown.read_text(
                encoding="utf-8"
            )

    return tuple(
        DocumentSet(label=label, contents=par_label[label])
        for label in sorted(par_label)
    )


def collect_corpus(
    epub_path: Path,
    caches: Mapping[str, Path],
    options: CorpusOptions,
) -> Corpus:
    """Assemble tout le corpus comparatif d'un run.

    Args:
        epub_path: EPUB source de la suite.
        caches: Cache par identifiant de variante, dans l'ordre de comparaison.
        options: Réglages d'extraction.

    Returns:
        Le corpus, dont les sections désactivées sont vides.
    """
    translation = (
        collect_translation(epub_path, caches, options) if options.translation else None
    )
    glossary = collect_documents(caches, PhaseName.GLOSSARY) if options.glossary else ()
    analysis = (
        collect_documents(caches, PhaseName.LITERARY_ANALYSIS)
        if options.analysis
        else ()
    )

    if translation is not None:
        logger.info(
            f"📚 Corpus : {len(translation.fragments)} fragment(s) retenu(s) sur "
            f"{translation.total} ({translation.identical} identique(s), "
            f"{translation.truncated} au-delà du plafond)"
        )

    return Corpus(
        variant_ids=tuple(caches),
        translation=translation,
        glossary=glossary,
        analysis=analysis,
    )


def variant_caches(work_root: Path, variant_ids: Sequence[str]) -> dict[str, Path]:
    """Chemins de cache des variantes, dans l'ordre donné.

    Args:
        work_root: Répertoire parent des workspaces.
        variant_ids: Variantes à retenir.

    Returns:
        Mapping `identifiant → cache`.
    """
    return {vid: work_root / vid / CACHE_DIRNAME for vid in variant_ids}
