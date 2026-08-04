"""Fixtures communes aux tests d'audit.

Les auditeurs lisent un cache de pipeline. Ces fixtures en fabriquent un
minimal — un dossier de phase, son sous-dossier `_v2` — sans passer par le
pipeline, qui exigerait un EPUB et des appels LLM.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from ebook_translator.pipeline.base import PhaseBase, PhaseName

TermeBrut = dict[str, str]


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """Répertoire de cache vide, comme en produit `StoreManager`."""
    cache = tmp_path / "livre" / ".livre_cache"
    cache.mkdir(parents=True)
    return cache


@pytest.fixture
def write_glossary_chunks(cache_dir: Path) -> Callable[..., Path]:
    """Écrit des chunks de glossaire dans le store v2 de la phase.

    Le store v2 est un mapping `clé de chunk → liste JSON sérialisée`, tel que
    l'écrit `MemoizedChunkPersister`.
    """
    import json

    def _write(chunks: dict[str, list[TermeBrut]]) -> Path:
        dossier = cache_dir / str(PhaseName.GLOSSARY) / PhaseBase.BYTE_STORE_SUBDIR
        dossier.mkdir(parents=True, exist_ok=True)
        charge = {cle: json.dumps(termes) for cle, termes in chunks.items()}
        _ = (dossier / "glossary_deadbeef.json").write_text(
            json.dumps(charge, ensure_ascii=False), encoding="utf-8"
        )
        return cache_dir

    return _write


def terme(
    nom: str,
    traduction: str,
    type_: str = "objet",
    sexe: str = "nc",
) -> TermeBrut:
    """Entrée de glossaire brute, telle que sérialisée par la phase.

    Args:
        nom: Terme source.
        traduction: Proposition de traduction.
        type_: Classement `type`.
        sexe: Classement `sexe`.

    Returns:
        Le dictionnaire attendu dans la charge du store.
    """
    return {
        "terme": nom,
        "type": type_,
        "sexe": sexe,
        "proposition_traduction": traduction,
    }
