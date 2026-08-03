"""
Isolation des variantes et amorçage des phases partagées.

Chaque variante s'exécute dans son propre répertoire, qui contient un lien vers
l'EPUB source et le cache de la variante. L'EPUB est lié plutôt que référencé
en place parce que le pipeline dérive plusieurs chemins d'écriture de
`epub_path.parent` — notamment l'export du glossaire
(`Pipeline._glossary_export_path`). Sans cette indirection, deux variantes du
même livre s'écraseraient mutuellement.

Les phases partagées sont **copiées** depuis le cache du run d'amorçage, pas
liées : une variante qui recalculerait une partie de la phase corromprait
sinon la référence commune de toutes les autres.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

from ebook_translator.bench.suite import RunEnv
from ebook_translator.logger import get_logger
from ebook_translator.pipeline.base import PhaseName

logger = get_logger(__name__)

CACHE_DIRNAME = "cache"
"""Nom du répertoire de cache dans le workspace d'une variante."""

OUTPUT_STEM_SUFFIX = " [traduit]"
"""Suffixe du nom de l'EPUB produit, pour le distinguer de la source liée."""


def prepare_workspace(work_root: Path, variant_id: str, epub: Path) -> RunEnv:
    """Crée le répertoire de travail isolé d'une variante.

    Args:
        work_root: Répertoire parent des workspaces du run.
        variant_id: Identifiant de la variante (ou du run d'amorçage).
        epub: EPUB source de la suite.

    Returns:
        Les emplacements à relayer au `PipelineBuilder` de la variante.

    Raises:
        FileNotFoundError: Si l'EPUB source est introuvable.
    """
    source = epub.resolve()
    if not source.exists():
        raise FileNotFoundError(f"EPUB source introuvable : {source}")

    workspace = work_root / variant_id
    workspace.mkdir(parents=True, exist_ok=True)

    link = workspace / source.name
    _link_or_copy(source, link)

    cache_dir = workspace / CACHE_DIRNAME
    cache_dir.mkdir(parents=True, exist_ok=True)

    output = workspace / f"{source.stem}{OUTPUT_STEM_SUFFIX}{source.suffix}"

    return RunEnv(
        variant_id=variant_id,
        epub=link,
        output=output,
        cache_dir=cache_dir,
        workspace=workspace,
    )


def _link_or_copy(source: Path, link: Path) -> None:
    """Pose un lien symbolique vers `source`, ou copie si les liens échouent.

    Args:
        source: Fichier source, déjà résolu.
        link: Emplacement du lien à créer. Remplacé s'il existe déjà.
    """
    if link.is_symlink() or link.exists():
        link.unlink()

    try:
        link.symlink_to(source)
    except OSError as error:
        # Systèmes sans droit de création de liens (Windows non élevé, certains
        # montages) : la copie coûte le poids du livre mais préserve l'isolation.
        logger.warning(f"Lien symbolique impossible ({error}) — copie de {source.name}")
        _ = shutil.copy2(source, link)


def seed_shared_phases(
    seed_cache: Path,
    target: RunEnv,
    phases: Sequence[PhaseName],
) -> list[PhaseName]:
    """Copie les stores des phases partagées dans le cache d'une variante.

    Le nom de répertoire d'un store est la clé de phase (`PhaseBase.store_key`,
    par défaut le nom de la phase), donc `<cache>/<nom de phase>/`.

    Args:
        seed_cache: Cache du run d'amorçage, source des stores partagés.
        target: Workspace de la variante à amorcer.
        phases: Phases dont le cache doit être repris.

    Returns:
        Les phases effectivement copiées, dans l'ordre reçu.

    Raises:
        FileNotFoundError: Si le store d'une phase demandée est absent du cache
            d'amorçage — signe que le seed ne déclarait pas cette phase, ou
            qu'il a échoué avant de l'exécuter.
    """
    copiees: list[PhaseName] = []

    for phase in phases:
        source = seed_cache / str(phase)
        if not source.is_dir():
            raise FileNotFoundError(
                f"Phase partagée '{phase}' absente du cache d'amorçage : {source}. "
                f"Le run d'amorçage déclare-t-il bien cette phase ?"
            )

        destination = target.cache_dir / str(phase)
        if destination.exists():
            shutil.rmtree(destination)
        _ = shutil.copytree(source, destination)

        copiees.append(phase)
        logger.info(f"  • Phase partagée '{phase}' amorcée → {target.variant_id}")

    return copiees
