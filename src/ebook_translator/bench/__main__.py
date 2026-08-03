"""
Ligne de commande du banc d'essais.

    uv run python -m ebook_translator.bench bench/config_exemple.py

Exécute la suite déclarée par le script, puis écrit le rapport comparatif dans
`bench/runs/<run_id>/`. L'arbitrage se fait ensuite avec `/bench-judge`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ebook_translator.bench.collect import collect_corpus, variant_caches
from ebook_translator.bench.report import write_report
from ebook_translator.bench.runner import DEFAULT_RUNS_DIR, SeedFailedError, run_suite
from ebook_translator.logger import get_logger

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Exécute une suite et écrit son rapport.

    Args:
        argv: Arguments de ligne de commande (par défaut `sys.argv[1:]`).

    Returns:
        Code de sortie : 0 si toutes les variantes ont abouti, 1 sinon.
    """
    parser = argparse.ArgumentParser(
        prog="python -m ebook_translator.bench",
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

    corpus = collect_corpus(
        run.suite.epub,
        variant_caches(run.work_root, [v.variant_id for v in run.variants]),
        run.suite.corpus,
    )
    racine = write_report(run, corpus)

    print(f"\n📁 Rapport : {racine}")
    print(f"⚖️  Arbitrage : /bench-judge {run.run_id}")

    if run.failed:
        echecs = ", ".join(v.variant_id for v in run.failed)
        print(f"⚠️  Variantes en échec : {echecs}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
