"""
Résolution de la matière auditée : un cache de pipeline, et rien d'autre.

L'audit ne rejoue aucune phase et n'émet aucun appel LLM. Tout ce qu'il examine
est déjà sur le disque : les stores écrits par `PhaseExecutor` pendant un run
ordinaire (`<epub_dir>/.<epub_stem>_cache/`) ou pendant un run de banc d'essais
(`bench/runs/<id>/work/<variant>/cache/`). Les deux ont la même forme, donc le
même auditeur les lit.

Chaque dossier de phase porte deux couches : le `Store` legacy à la racine et le
`FileByteStore` v2 dans `_v2/` (`PhaseBase.BYTE_STORE_SUBDIR`). Comme dans
`bench.collect.read_translations`, le v2 passe en dernier et fait foi.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import cast

from ebooklib import epub

from ebook_translator.htmlpage import HtmlPage
from ebook_translator.logger import get_logger
from ebook_translator.pipeline.base import PhaseBase, PhaseName
from ebook_translator.translation.epub_handler import (
    extract_html_items_in_spine_order,
)

logger = get_logger(__name__)

TRANSLATED_MARKER = "[traduit]"
"""Suffixe des EPUB produits par le pipeline — à ne pas prendre pour la source."""


class AuditSourceError(Exception):
    """La matière demandée est absente ou inexploitable."""


@dataclass(frozen=True)
class AuditSource:
    """Accès en lecture seule au cache d'un run et à son EPUB source.

    Attributes:
        cache_dir: Répertoire de cache du run, contenant un dossier par phase.
        epub_path: EPUB source, ou `None` s'il n'a pas été trouvé. Les métriques
            qui confrontent la sortie au texte d'origine sont alors omises
            plutôt que calculées sur une base fausse.
    """

    cache_dir: Path
    epub_path: Path | None = None

    @classmethod
    def resolve(cls, cache_dir: Path, epub_path: Path | None = None) -> AuditSource:
        """Construit une source à partir d'un répertoire de cache.

        L'EPUB est déduit du répertoire parent du cache quand il n'est pas donné :
        c'est là que le pipeline et le banc d'essais le posent tous les deux. Les
        EPUB portant `[traduit]` sont écartés — ce sont des sorties, pas la source.

        Args:
            cache_dir: Répertoire de cache à auditer.
            epub_path: EPUB source explicite, prioritaire sur la déduction.

        Returns:
            La source résolue.

        Raises:
            AuditSourceError: Si `cache_dir` n'est pas un répertoire, ou si
                l'`epub_path` fourni n'existe pas.
        """
        if not cache_dir.is_dir():
            raise AuditSourceError(f"Cache introuvable : {cache_dir}")

        if epub_path is not None:
            if not epub_path.is_file():
                raise AuditSourceError(f"EPUB introuvable : {epub_path}")
            return cls(cache_dir=cache_dir, epub_path=epub_path)

        return cls(cache_dir=cache_dir, epub_path=_find_source_epub(cache_dir.parent))

    def phase_dir(self, phase: PhaseName) -> Path:
        """Répertoire de store d'une phase.

        Args:
            phase: Phase demandée.

        Returns:
            Le répertoire de la phase dans le cache.

        Raises:
            AuditSourceError: Si la phase n'a rien écrit dans ce cache.
        """
        dossier = self.cache_dir / str(phase)
        if not dossier.is_dir():
            raise AuditSourceError(
                f"La phase « {phase} » n'a rien écrit dans {self.cache_dir}. "
                f"Phases présentes : {', '.join(self.available_phases()) or 'aucune'}"
            )
        return dossier

    def available_phases(self) -> tuple[str, ...]:
        """Phases ayant écrit dans ce cache.

        Returns:
            Les noms de dossier présents, triés.
        """
        return tuple(sorted(d.name for d in self.cache_dir.iterdir() if d.is_dir()))

    def markdown_documents(self, phase: PhaseName) -> dict[str, str]:
        """Markdown de revue exportés par une phase.

        Args:
            phase: Phase dont on lit les exports.

        Returns:
            Mapping `nom de fichier sans extension → contenu`, trié par nom.
        """
        dossier = self.phase_dir(phase)
        return {
            fichier.stem: fichier.read_text(encoding="utf-8")
            for fichier in sorted(dossier.glob("*.md"))
        }

    def byte_store_payloads(self, phase: PhaseName) -> dict[str, str]:
        """Charges brutes du `FileByteStore` v2 d'une phase.

        Chaque fichier `_v2/*.json` est un mapping `clé → charge sérialisée`. Les
        fichiers sont fusionnés ; une clé présente deux fois — cas qui ne devrait
        pas se produire, les clés portant un fingerprint — est journalisée.

        Args:
            phase: Phase dont on lit le store v2.

        Returns:
            Mapping `clé de chunk → charge JSON sérialisée`.
        """
        dossier = self.phase_dir(phase) / PhaseBase.BYTE_STORE_SUBDIR
        fusion: dict[str, str] = {}
        if not dossier.is_dir():
            return fusion

        for fichier in sorted(dossier.glob("*.json")):
            contenu = _load_json_mapping(fichier)
            for cle, charge in contenu.items():
                if cle in fusion:
                    logger.warning(f"Clé dupliquée dans {dossier} : {cle}")
                fusion[cle] = charge
        return fusion

    @cached_property
    def source_fragments(self) -> tuple[str, ...]:
        """Fragments traduisibles du livre source, dans l'ordre du spine.

        Vide quand aucun EPUB n'a pu être résolu.

        Returns:
            Les textes source, un par fragment.
        """
        if self.epub_path is None:
            logger.warning(
                "Aucun EPUB source : les métriques confrontant la sortie au texte "
                "d'origine seront omises."
            )
            return ()

        book = epub.read_epub(self.epub_path)  # pyright: ignore[reportUnknownMemberType]
        html_items, _ = extract_html_items_in_spine_order(book)

        fragments: list[str] = []
        for item in html_items:
            fragments.extend(texte for _, texte in HtmlPage(item).dump())
        return tuple(fragments)

    @cached_property
    def source_text(self) -> str:
        """Texte source concaténé, un fragment par ligne.

        Returns:
            Le texte du livre, vide si aucun EPUB n'a été résolu.
        """
        return "\n".join(self.source_fragments)


def _find_source_epub(directory: Path) -> Path | None:
    """Cherche l'EPUB source dans un répertoire de travail.

    Args:
        directory: Répertoire à inspecter, sans récursion.

    Returns:
        Le premier EPUB ne portant pas le marqueur de sortie, ou `None`.
    """
    if not directory.is_dir():
        return None
    candidats = [
        chemin
        for chemin in sorted(directory.glob("*.epub"))
        if TRANSLATED_MARKER not in chemin.name
    ]
    if not candidats:
        return None
    if len(candidats) > 1:
        logger.warning(
            f"Plusieurs EPUB source dans {directory}, retenu : {candidats[0].name}"
        )
    return candidats[0]


def _load_json_mapping(path: Path) -> dict[str, str]:
    """Lit un fichier JSON attendu sous forme de mapping de chaînes.

    Args:
        path: Fichier à lire.

    Returns:
        Le mapping, vide si le fichier est illisible ou d'une autre forme.
    """
    try:
        contenu: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as erreur:
        logger.warning(f"Store illisible ignoré : {path} ({erreur})")
        return {}

    if not isinstance(contenu, dict):
        logger.warning(f"Store de forme inattendue ignoré : {path}")
        return {}

    brut = cast(dict[object, object], contenu)
    return {str(cle): valeur for cle, valeur in brut.items() if isinstance(valeur, str)}
