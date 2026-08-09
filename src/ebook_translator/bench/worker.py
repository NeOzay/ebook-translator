"""
Point d'entrée du sous-processus qui exécute **une** variante.

Un run de pipeline gèle `CommunContext` et peuple les singletons `HtmlPage` :
le processus est brûlé après un run. Le harness lance donc un fils par
variante, qui construit le pipeline depuis le script de configuration puis
dépose son résultat en JSON dans le workspace.

Invocation (faite par `runner.py`, pas à la main) :

    python -m ebook_translator.bench.worker \\
        --config bench/config_exemple.py --variant t05 --work-root <run>/work
"""

from __future__ import annotations

import argparse
import time
import traceback
from pathlib import Path

from ebook_translator.bench.results import (
    RESULT_FILENAME,
    PhaseResult,
    VariantResult,
    compute_status,
    describe_shortfall,
)
from ebook_translator.bench.suite import RunEnv, load_suite
from ebook_translator.bench.workspace import prepare_workspace, variant_logs_dir
from ebook_translator.logger import LogSession, get_logger

logger = get_logger(__name__)


def _check_env_honored(pipeline_epub: Path, pipeline_cache: Path, env: RunEnv) -> None:
    """Vérifie que la fabrique a bien relayé les chemins imposés.

    Une fabrique qui code en dur son EPUB ou son cache ferait fuiter les
    variantes les unes dans les autres — caches croisés, glossaires écrasés —
    et le résultat de la comparaison ne voudrait plus rien dire. L'échec est
    donc immédiat et explicite.

    Args:
        pipeline_epub: EPUB retenu par le pipeline construit.
        pipeline_cache: Cache retenu par le pipeline construit.
        env: Emplacements imposés à la variante.

    Raises:
        ValueError: Si l'un des deux chemins ne correspond pas.
    """
    ecarts: list[str] = []
    if pipeline_epub.resolve() != env.epub.resolve():
        ecarts.append(f"epub : attendu {env.epub}, obtenu {pipeline_epub}")
    if pipeline_cache.resolve() != env.cache_dir.resolve():
        ecarts.append(f"cache_dir : attendu {env.cache_dir}, obtenu {pipeline_cache}")

    if ecarts:
        raise ValueError(
            "La fabrique de la variante n'a pas relayé les chemins du RunEnv "
            "(.epub(env.epub) / .cache_dir(env.cache_dir) manquants ?) :\n  - "
            + "\n  - ".join(ecarts)
        )


def execute(config_path: Path, variant_id: str, work_root: Path) -> VariantResult:
    """Exécute une variante et renvoie son résultat.

    Args:
        config_path: Script de configuration exposant la suite.
        variant_id: Variante à exécuter, ou `SEED_ID` pour le run d'amorçage.
        work_root: Répertoire parent des workspaces du run.

    Returns:
        Le résultat de la variante ; `status == "error"` si le pipeline a levé.
    """
    start = time.time()
    suite = load_suite(config_path)
    env = prepare_workspace(work_root, variant_id, suite.epub)

    try:
        builder = suite.factory(variant_id)(env)
        pipeline, run_kwargs = builder.build()
        _check_env_honored(pipeline.epub_path, pipeline.cache_dir, env)

        stats = pipeline.run(**run_kwargs)  # pyright: ignore[reportArgumentType]

        phases = tuple(PhaseResult.from_stats(s) for s in stats.values())
        status = compute_status(phases)

        # Un pipeline qui rend la main sans exception n'a pas forcément
        # travaillé : une limitation de débit épuisée en silence produit un run
        # vide, que le banc déclarait « ok » (run de banc vide déclaré réussi, 2026-08-04).
        message: str | None = None
        if status != "ok":
            shortfall = describe_shortfall(phases) or "aucune phase n'a de travail"
            message = (
                f"Variante '{variant_id}' incomplète ({shortfall}). "
                f"Voir logs/translation.log dans le workspace de la variante."
            )
            logger.error(f"❌ {message}")

        return VariantResult(
            variant_id=variant_id,
            status=status,
            phases=phases,
            duration_seconds=time.time() - start,
            error=message,
        )

    except Exception as error:
        logger.exception(f"Variante '{variant_id}' en échec : {error}")
        return VariantResult(
            variant_id=variant_id,
            status="error",
            duration_seconds=time.time() - start,
            error=f"{type(error).__name__}: {error}\n{traceback.format_exc()}",
        )


def main(argv: list[str] | None = None) -> int:
    """Exécute la variante demandée et écrit `result.json` dans son workspace.

    Les logs sont redirigés vers le workspace de la variante avant toute
    exécution : sans cela, ils atterriraient dans le `logs/run_<horodatage>/`
    du répertoire courant, sans rattachement au run ni à la variante.

    Args:
        argv: Arguments de ligne de commande (par défaut `sys.argv[1:]`).

    Returns:
        Code de sortie : 0 si la variante a abouti, 1 sinon.
    """
    parser = argparse.ArgumentParser(
        prog="python -m ebook_translator.bench.worker",
        description="Exécute une variante de banc d'essais (usage interne).",
    )
    _ = parser.add_argument("--config", required=True, type=Path)
    _ = parser.add_argument("--variant", required=True)
    _ = parser.add_argument("--work-root", required=True, type=Path)
    args = parser.parse_args(argv)

    config_path: Path = args.config
    variant_id: str = args.variant
    work_root: Path = args.work_root

    LogSession.redirect(variant_logs_dir(work_root, variant_id))

    result = execute(config_path, variant_id, work_root)
    result.write(work_root / variant_id / RESULT_FILENAME)

    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
