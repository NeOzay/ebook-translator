"""
Orchestration d'un run de banc d'essais.

Le run d'amorçage s'exécute d'abord, puis chaque variante, **séquentiellement**
et dans son propre sous-processus. Le séquencement n'est pas une limitation
technique : des variantes concurrentes se disputeraient le débit de l'API et
leurs durées ne seraient plus comparables.

Un échec de variante n'interrompt pas le run — les autres variantes gardent
leur intérêt et le rapport signale la défaillante. Un échec du run d'amorçage,
lui, arrête tout : les variantes en dépendent.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ebook_translator.bench.results import RESULT_FILENAME, VariantResult
from ebook_translator.bench.suite import (
    LOGS_DIRNAME,
    SEED_ID,
    BenchSuite,
    Variant,
    load_suite,
)
from ebook_translator.bench.workspace import prepare_workspace, seed_shared_phases
from ebook_translator.logger import LogSession, get_logger

logger = get_logger(__name__)

DEFAULT_RUNS_DIR = Path("bench/runs")
"""Emplacement par défaut des runs, relatif au répertoire de travail."""

WORK_DIRNAME = "work"
"""Sous-répertoire du run contenant les workspaces des variantes."""

CONFIG_COPY_NAME = "config.py"
"""Copie du script de configuration, conservée avec le run pour traçabilité."""


class SeedFailedError(RuntimeError):
    """Le run d'amorçage a échoué : les variantes ne sont pas comparables."""


@dataclass(frozen=True)
class BenchRun:
    """Un run complet et ses résultats.

    Attributes:
        run_id: Identifiant horodaté du run.
        root: Répertoire du run.
        suite: Suite exécutée.
        config_path: Script de configuration d'origine.
        seed: Résultat du run d'amorçage, `None` s'il n'y en avait pas.
        variants: Résultats par variante, dans l'ordre de déclaration.
    """

    run_id: str
    root: Path
    suite: BenchSuite
    config_path: Path
    seed: VariantResult | None
    variants: tuple[VariantResult, ...]

    @property
    def work_root(self) -> Path:
        """Répertoire parent des workspaces des variantes."""
        return self.root / WORK_DIRNAME

    @property
    def succeeded(self) -> tuple[VariantResult, ...]:
        """Variantes allées au bout du pipeline.

        Seules celles-ci sont comparables : une variante incomplète fausserait
        l'arbitrage en présentant moins de matière que les autres.
        """
        return tuple(v for v in self.variants if v.status == "ok")

    @property
    def partial(self) -> tuple[VariantResult, ...]:
        """Variantes qui ont travaillé sans aller au bout."""
        return tuple(v for v in self.variants if v.status == "partial")

    @property
    def failed(self) -> tuple[VariantResult, ...]:
        """Variantes en échec."""
        return tuple(v for v in self.variants if v.status == "error")


def new_run_id(now: datetime | None = None) -> str:
    """Identifiant horodaté d'un run.

    Args:
        now: Instant de référence (par défaut, maintenant).

    Returns:
        Identifiant de la forme `20260802_143005`.
    """
    return (now or datetime.now()).strftime("%Y%m%d_%H%M%S")


def run_suite(
    config_path: Path | str,
    runs_dir: Path | str = DEFAULT_RUNS_DIR,
    run_id: str | None = None,
    only: Sequence[str] | None = None,
) -> BenchRun:
    """Exécute une suite complète et renvoie ses résultats.

    Args:
        config_path: Script de configuration exposant la suite.
        runs_dir: Répertoire où créer le run.
        run_id: Identifiant du run (horodaté par défaut).
        only: Sous-ensemble de variantes à exécuter. Les autres sont ignorées ;
            utile pour relancer une variante défaillante dans un run neuf.

    Returns:
        Le run et ses résultats.

    Raises:
        SeedFailedError: Si le run d'amorçage échoue.
        KeyError: Si `only` cite une variante non déclarée.
    """
    config = Path(config_path).resolve()
    suite = load_suite(config)

    selection = _select(suite, only)

    run_id = run_id or new_run_id()
    root = Path(runs_dir) / run_id
    work_root = root / WORK_DIRNAME
    work_root.mkdir(parents=True, exist_ok=True)
    _ = shutil.copy2(config, root / CONFIG_COPY_NAME)

    # Rattache la trace du harness au run — et, du même coup, celle de la
    # collecte et du rapport, qui s'exécutent ensuite dans ce processus.
    LogSession.redirect(root / LOGS_DIRNAME)

    logger.info(f"🏁 Banc d'essais {run_id} — {len(selection)} variante(s)")

    seed_result: VariantResult | None = None
    seed_cache: Path | None = None

    if suite.seed is not None:
        logger.info(f"🌱 Run d'amorçage (phases partagées : {suite.shared_phases})")
        seed_env = prepare_workspace(work_root, SEED_ID, suite.epub)
        seed_result = _execute_variant(config, SEED_ID, work_root)
        if seed_result.status != "ok":
            raise SeedFailedError(
                f"Le run d'amorçage a échoué, les variantes ne seraient pas "
                f"comparables :\n{seed_result.error}"
            )
        seed_cache = seed_env.cache_dir

    results: list[VariantResult] = []
    for position, variant in enumerate(selection, start=1):
        logger.info(f"▶️  Variante {position}/{len(selection)} : {variant.id}")

        env = prepare_workspace(work_root, variant.id, suite.epub)
        seeded = (
            seed_shared_phases(seed_cache, env, suite.shared_phases)
            if seed_cache is not None
            else []
        )

        result = _execute_variant(config, variant.id, work_root)
        if seeded:
            result = _with_seeded(result, seeded)
            result.write(env.workspace / RESULT_FILENAME)
        results.append(result)

        if result.status != "ok":
            logger.error(f"❌ Variante '{variant.id}' en échec — run poursuivi")

    return BenchRun(
        run_id=run_id,
        root=root,
        suite=suite,
        config_path=config,
        seed=seed_result,
        variants=tuple(results),
    )


def _select(suite: BenchSuite, only: Sequence[str] | None) -> list[Variant]:
    """Variantes à exécuter, dans l'ordre de déclaration.

    Args:
        suite: Suite chargée.
        only: Identifiants retenus, ou `None` pour tout exécuter.

    Returns:
        Les variantes sélectionnées.

    Raises:
        KeyError: Si un identifiant demandé n'existe pas.
    """
    if only is None:
        return list(suite.variants)

    demandes = list(only)
    for variant_id in demandes:
        _ = suite.variant(variant_id)  # lève KeyError si inconnu
    return [v for v in suite.variants if v.id in set(demandes)]


def _with_seeded(result: VariantResult, seeded: Sequence[str]) -> VariantResult:
    """Réécrit un résultat en y notant les phases servies par l'amorçage."""
    return VariantResult(
        variant_id=result.variant_id,
        status=result.status,
        phases=result.phases,
        duration_seconds=result.duration_seconds,
        error=result.error,
        seeded_phases=tuple(str(phase) for phase in seeded),
    )


def _execute_variant(config: Path, variant_id: str, work_root: Path) -> VariantResult:
    """Lance le sous-processus d'une variante et relit son résultat.

    La sortie du fils n'est pas capturée : les barres de progression et les
    logs du pipeline restent visibles pendant le run, qui dure des minutes.

    Args:
        config: Script de configuration.
        variant_id: Variante à exécuter.
        work_root: Répertoire parent des workspaces.

    Returns:
        Le résultat relu depuis le workspace ; un résultat d'erreur synthétique
        si le fils est mort avant d'avoir pu l'écrire.
    """
    result_path = work_root / variant_id / RESULT_FILENAME
    if result_path.exists():
        result_path.unlink()

    command = [
        sys.executable,
        "-m",
        "ebook_translator.bench.worker",
        "--config",
        str(config),
        "--variant",
        variant_id,
        "--work-root",
        str(work_root),
    ]

    completed = subprocess.run(command, check=False)

    if not result_path.exists():
        return VariantResult(
            variant_id=variant_id,
            status="error",
            error=(
                f"Le sous-processus s'est terminé (code {completed.returncode}) "
                f"sans écrire {RESULT_FILENAME} — interruption ou crash."
            ),
        )

    return VariantResult.read(result_path)
