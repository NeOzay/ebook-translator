"""
Ligne de commande du banc d'essais.

    uv run ebook-bench bench/config_exemple.py

Exécute la suite déclarée par le script, puis écrit le rapport comparatif dans
`bench/runs/<run_id>/`. L'arbitrage se fait ensuite avec `/bench-judge`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ebook_translator.bench.collect import collect_corpus, variant_caches
from ebook_translator.bench.report import write_report
from ebook_translator.bench.runner import DEFAULT_RUNS_DIR, SeedFailedError, run_suite
from ebook_translator.cli import program_name
from ebook_translator.logger import get_logger

logger = get_logger(__name__)

MODULE_INVOCATION = "python -m ebook_translator.bench"
"""Forme longue, à afficher quand la commande est lancée par `-m`."""


def main(argv: list[str] | None = None) -> int:
    """Exécute une suite et écrit son rapport.

    Args:
        argv: Arguments de ligne de commande (par défaut `sys.argv[1:]`).

    Returns:
        Code de sortie : 0 si toutes les variantes ont abouti, 1 sinon.
    """
    parser = argparse.ArgumentParser(
        prog=program_name(MODULE_INVOCATION),
        description="Compare plusieurs configurations de pipeline sur un même livre.",
    )
    _ = parser.add_argument(
        "config", type=Path, help="Script exposant `suite = BenchSuite(...)`"
    )
    _ = parser.add_argument(
        "--runs-dir",
        type=Path,
        default=DEFAULT_RUNS_DIR,
        help=f"Répertoire des runs (défaut : {DEFAULT_RUNS_DIR})",
    )
    _ = parser.add_argument(
        "--run-id", default=None, help="Identifiant du run (horodaté par défaut)"
    )
    _ = parser.add_argument(
        "--only",
        default=None,
        help="Variantes à exécuter, séparées par des virgules",
    )
    args = parser.parse_args(argv)

    config: Path = args.config
    runs_dir: Path = args.runs_dir
    run_id: str | None = args.run_id
    only = [part.strip() for part in args.only.split(",")] if args.only else None

    try:
        run = run_suite(config, runs_dir=runs_dir, run_id=run_id, only=only)
    except SeedFailedError as error:
        logger.error(f"❌ {error}")
        return 1

    # Le corpus n'est bâti que sur les variantes complètes : une variante
    # incomplète y apporterait moins de matière que les autres, et l'arbitre
    # comparerait des volumes plutôt que des traductions.
    corpus = collect_corpus(
        run.suite.epub,
        variant_caches(run.work_root, [v.variant_id for v in run.succeeded]),
        run.suite.corpus,
    )
    racine = write_report(run, corpus)

    print(f"\n📁 Rapport : {racine}")
    print(f"⚖️  Arbitrage : /bench-judge {run.run_id}")

    if run.partial:
        partielles = ", ".join(v.variant_id for v in run.partial)
        print(f"⚠️  Variantes incomplètes, écartées du corpus : {partielles}")

    if run.failed:
        echecs = ", ".join(v.variant_id for v in run.failed)
        print(f"⚠️  Variantes en échec : {echecs}")

    if run.failed or run.partial:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
