"""Couche bytes-only des stores.

Fournit `ByteStore`, Protocol minimal manipulant des octets adressés par
clé, et deux implémentations concrètes :

- `FileByteStore` : un fichier JSON (ou autre) par clé sur disque, avec
  lock par-fichier partagé globalement et écriture atomique
  (tempfile + ``os.replace``).
- `MemoryByteStore` : `dict[str, bytes]` thread-safe, utilisé pour les
  tests.

La logique sémantique (modèle Pydantic, projection chunk, fallback,
merge) **ne vit pas ici**. Cette couche ne sait que persister/lire des
octets ; les `ChunkPersister` (cf. ``persistence/``) la composent.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import threading
import time
import uuid
from collections.abc import Generator, Iterable
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Protocol


class ByteStore(Protocol):
    """Interface octets-only des stores.

    Une clé arbitraire (str) → contenu binaire. Pas de notion de
    sérialisation, de schéma, de chunk : c'est l'affaire du caller (un
    `ChunkPersister` typiquement).
    """

    def read(self, key: str) -> bytes | None:
        """Lit le contenu associé à `key`. Renvoie `None` si absent."""
        ...

    def write(self, key: str, data: bytes) -> None:
        """Écrit `data` sous `key`, écrasant toute valeur existante.

        Doit être atomique vis-à-vis de lecteurs concurrents : un lecteur
        observe soit l'ancienne valeur, soit la nouvelle, jamais une
        valeur partielle.
        """
        ...

    def delete(self, key: str) -> None:
        """Supprime l'entrée `key` si présente. No-op sinon."""
        ...

    def exists(self, key: str) -> bool:
        """Vrai si une valeur est associée à `key`."""
        ...

    def list_keys(self) -> Iterable[str]:
        """Énumère les clés présentes."""
        ...

    def lock(self, key: str) -> AbstractContextManager[None]:
        """Acquiert un lock dédié à `key` (réentrant côté caller).

        Utilisé pour des séquences read-modify-write atomiques côté
        caller (ex. merge d'un payload existant).
        """
        ...


@contextmanager
def _wrap_lock(lock: threading.RLock) -> Generator[None]:
    """Adapte `threading.RLock` au type `AbstractContextManager[None]`.

    `threading.RLock.__enter__` retourne `bool`, ce qui ne satisfait pas
    le protocole `AbstractContextManager[None]`. Ce wrapper masque le
    retour booléen.
    """

    lock.acquire()
    try:
        yield
    finally:
        lock.release()


_FILE_LOCKS: dict[str, threading.RLock] = {}
_FILE_LOCKS_GUARD = threading.RLock()


def _file_lock(path: Path) -> threading.RLock:
    """Lock partagé globalement par chemin absolu."""

    abs_path = str(path.absolute())
    with _FILE_LOCKS_GUARD:
        if abs_path not in _FILE_LOCKS:
            _FILE_LOCKS[abs_path] = threading.RLock()
        return _FILE_LOCKS[abs_path]


def _safe_filename(key: str) -> str:
    """Dérive un nom de fichier sûr depuis une clé arbitraire.

    Combine un nom assaini et un hash MD5 court : garantit l'unicité
    même si deux clés normalisent vers le même nom (`"a/b"` et `"a_b"`).
    """

    safe = key.replace("\\", "_").replace("/", "_").replace(":", "")
    digest = hashlib.md5(key.encode()).hexdigest()[:8]
    return f"{safe}_{digest}.json"


def _atomic_write(path: Path, data: bytes) -> None:
    """Écrit `data` dans `path` via tempfile + `os.replace`.

    Robuste face aux écritures concurrentes (Lock côté caller) et aux
    interruptions (le fichier final n'apparaît qu'après rename atomique).
    Retries courts sur `PermissionError` (Windows).
    """

    temp = path.with_suffix(f"{path.suffix}.tmp.{uuid.uuid4().hex[:8]}")
    try:
        with open(temp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(3):
            try:
                os.replace(str(temp), str(path))
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.01)
    except OSError:
        if temp.exists():
            with contextlib.suppress(Exception):
                temp.unlink()
        raise


class FileByteStore(ByteStore):
    """`ByteStore` adossé au filesystem.

    Un fichier par clé (`<safe_name>_<hash>.json`) dans `cache_dir`.
    Lock par fichier partagé globalement (deux instances pointant le
    même fichier se synchronisent). Écriture atomique.

    Attributes:
        cache_dir: Répertoire absolu où vivent les fichiers. Créé s'il
            n'existe pas.
    """

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir.absolute()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.cache_dir / _safe_filename(key)

    def read(self, key: str) -> bytes | None:
        path = self._path(key)
        if not path.exists():
            return None
        with _file_lock(path):
            try:
                with open(path, "rb") as f:
                    return f.read()
            except OSError:
                return None

    def write(self, key: str, data: bytes) -> None:
        path = self._path(key)
        with _file_lock(path):
            _atomic_write(path, data)

    def delete(self, key: str) -> None:
        path = self._path(key)
        with _file_lock(path):
            if path.exists():
                with contextlib.suppress(OSError):
                    path.unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def list_keys(self) -> Iterable[str]:
        # Le mapping inverse safe_name→key n'est pas reconstructible :
        # on retourne donc les noms de fichier (sans .json) comme clés
        # opaques. Convient à l'usage interne (énumération pour clear).
        for f in self.cache_dir.glob("*.json"):
            yield f.stem

    def lock(self, key: str) -> AbstractContextManager[None]:
        return _wrap_lock(_file_lock(self._path(key)))


class MemoryByteStore(ByteStore):
    """`ByteStore` en mémoire, thread-safe. Pour tests uniquement."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.RLock()

    def _lock_for(self, key: str) -> threading.RLock:
        with self._guard:
            if key not in self._locks:
                self._locks[key] = threading.RLock()
            return self._locks[key]

    def read(self, key: str) -> bytes | None:
        with self._lock_for(key):
            return self._data.get(key)

    def write(self, key: str, data: bytes) -> None:
        with self._lock_for(key):
            self._data[key] = data

    def delete(self, key: str) -> None:
        with self._lock_for(key):
            self._data.pop(key, None)

    def exists(self, key: str) -> bool:
        with self._lock_for(key):
            return key in self._data

    def list_keys(self) -> Iterable[str]:
        with self._guard:
            return list(self._data.keys())

    def lock(self, key: str) -> AbstractContextManager[None]:
        return _wrap_lock(self._lock_for(key))
