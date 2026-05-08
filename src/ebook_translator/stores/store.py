"""
Store pour sauvegarder et récupérer les traductions sur disque.

Ce module fournit une classe Store pour gérer la persistance des traductions
d'ebooks. Les traductions sont stockées au format JSON avec le numéro de ligne
(index) ou le texte original comme clé, et le texte traduit comme valeur.

Format de stockage:
    Format simplifié: {str(int): str, str: str}
    - Les clés peuvent être soit des index de ligne (convertis en string par JSON)
    - Soit des textes originaux (pour fallback de rétrocompatibilité)

Notes d'implémentation:
    - JSON sérialise les clés int en string, donc {"0": "Hello", "1": "World"}
    - Le store accepte à la fois int et str comme clés pour la flexibilité
    - La recherche se fait d'abord par index, puis par texte original si disponible
"""

import contextlib
import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from ebook_translator.segmentation.chunk import ChunkProtocol

from ..logger import get_logger

if TYPE_CHECKING:
    from ..htmlpage import TagKey
    from ..segmentation.segmentator import Chunk

logger = get_logger(__name__)

_data_cache: dict[Path, dict[str, str]] = {}

_lockfiles: dict[str, threading.Lock] = {}

_global_lock = threading.Lock()  # Lock global pour protéger l'accès aux caches et locks


def _get_lock_for_file(cache_file: Path) -> threading.Lock:
    """Récupère ou crée un Lock pour un fichier de cache donné.

    Args:
        cache_file: Chemin du fichier de cache

    Returns:
        Lock associé à ce fichier de cache
    """
    cache_key = str(cache_file.absolute())
    with _global_lock:  # Protéger l'accès au dict des locks
        if cache_key not in _lockfiles:
            _lockfiles[cache_key] = threading.Lock()
        return _lockfiles[cache_key]


def _load_cache(cache_file: Path) -> dict[str, str]:
    """
    Charge un fichier de cache JSON de manière thread-safe.

    Le cache contient un dictionnaire plat où les clés peuvent être :
    - Des index de ligne (sérialisés en string par JSON) : "0", "1", "2"...
    - Des textes originaux (pour fallback) : "Hello world", "Goodbye"...

    Args:
        cache_file: Chemin du fichier de cache

    Returns:
        Dictionnaire {clé: texte_traduit} où clé peut être int ou str
        Retourne un dictionnaire vide si le fichier n'existe pas ou en cas d'erreur

    Note:
        Thread-safe : Utilise un Lock par fichier pour éviter les lectures
        pendant qu'un autre thread écrit (PermissionError sur Windows).
    """
    if not cache_file.exists():
        return {}

    file_lock = _get_lock_for_file(cache_file)

    with file_lock:  # Bloquer pendant la lecture
        try:
            # Lire le contenu, puis fermer explicitement avant de parser
            # Cela garantit que le fichier est fermé au niveau OS avant de retourner
            with open(cache_file, encoding="utf-8") as f:
                content = f.read()

            # Parser après fermeture du fichier
            data: dict[str, str] = json.loads(content)
            return data

        except OSError as e:
            logger.error(f"Erreur lecture cache {cache_file.name}: {e}")
            return {}
        except json.JSONDecodeError as e:
            logger.warning(f"Cache corrompu {cache_file.name}: {e}")
            # Tenter de sauvegarder une backup avant de retourner un cache vide
            backup_file = cache_file.with_suffix(".json.backup")
            try:
                cache_file.rename(backup_file)
                logger.info(f"Backup sauvegardée: {backup_file.name}")
            except Exception:
                pass
            return {}


def _save_cache(cache_file: Path, translations_by_index: dict[str, str]) -> None:
    """
    Sauvegarde les traductions dans un fichier de cache JSON de manière thread-safe.

    Les clés int sont converties en string par la sérialisation JSON.
    Format de sortie : {"0": "Bonjour", "1": "Monde", ...}

    Args:
        cache_file: Chemin du fichier de cache
        translations_by_index: Dictionnaire {index: texte_traduit}

    Raises:
        IOError: Si l'écriture du fichier échoue (erreur critique)

    Note:
        Thread-safe : Utilise un Lock par fichier pour éviter les écritures
        concurrentes et les PermissionError sur Windows. Plus besoin de retry!
    """
    data = dict(
        sorted(
            translations_by_index.items(),
            key=lambda item: int(item[0]) if item[0].isdigit() else item[0],
        )
    )

    file_lock = _get_lock_for_file(cache_file)

    with file_lock:  # Bloquer pendant l'écriture
        # Utiliser un nom temporaire UNIQUE pour éviter les collisions
        # (même si le Lock garantit l'exclusivité, mieux vaut être prudent)
        temp_file = cache_file.with_suffix(f".json.tmp.{uuid.uuid4().hex[:8]}")
        try:
            # Écrire dans un fichier temporaire
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                # Forcer flush avant fermeture (important sur Windows)
                f.flush()
                os.fsync(f.fileno())

                # Renommer de manière atomique avec os.replace()
                # Retry court uniquement pour os.replace() (Windows peut mettre du temps à libérer le verrou)
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        os.replace(str(temp_file), str(cache_file))
                        break  # Succès
                    except PermissionError:
                        if attempt == max_retries - 1:
                            raise  # Dernière tentative échouée
                        # Micro-délai pour laisser Windows libérer le verrou
                        time.sleep(0.01)  # 10ms

        except OSError as e:
            logger.error(f"❌ Erreur sauvegarde cache {cache_file.name}: {e}")
            # Nettoyer le fichier temporaire si nécessaire
            if temp_file.exists():
                with contextlib.suppress(Exception):
                    temp_file.unlink()
                raise  # Re-lever car c'est critique


def _clear_cache() -> None:
    with _global_lock:
        _data_cache.clear()
        for name, lock in _lockfiles.items():
            if not lock.locked():
                _lockfiles.pop(name)


class Store:
    """
    Gestionnaire de persistance pour les traductions d'ebooks.

    Les traductions sont sauvegardées au format JSON avec l'index de ligne
    (ou le texte original) comme clé et le texte traduit comme valeur.
    Le nom du fichier de cache est dérivé du chemin du fichier source
    pour faciliter l'identification.

    Attributes:
        cache_dir: Répertoire où sont stockés les fichiers de cache
    """

    def __init__(self, cache_dir: Path, fallback: Store | None = None) -> None:
        """
        Initialise le store avec un répertoire de cache.

        Args:
            cache_dir: Répertoire où sauvegarder les fichiers de traduction.
                      Créé automatiquement s'il n'existe pas.
        """
        self.cache_dir = cache_dir.absolute()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._key_cache = str(self.cache_dir)
        self._fallback = fallback
        # Protection thread-safe : Lock par fichier de cache
        # Clé = chemin absolu du fichier cache, Valeur = Lock dédié
        self._file_locks: dict[str, threading.Lock] = {}
        self._file_locks_lock = threading.Lock()  # Protéger accès au dict lui-même

    def _get_cache_file_name(self, source_file: str | Path) -> Path:
        """
        Génère le chemin du fichier de cache basé sur le fichier source.

        Le nom du fichier combine le chemin source (sécurisé pour le système de
        fichiers) et un hash court pour garantir l'unicité.

        Args:
            source_file: Chemin du fichier source

        Returns:
            Path du fichier de cache JSON
        """
        source_file = str(source_file)
        # Convertit le chemin en un nom de fichier sûr
        safe_name = source_file.replace("\\", "_").replace("/", "_").replace(":", "")

        # Hash court pour garantir l'unicité
        file_hash = hashlib.md5(source_file.encode()).hexdigest()[:8]

        return self.cache_dir / f"{safe_name}_{file_hash}.json"

    def _get(
        self, file_name: Path | str, line_index: str, use_fallback: bool
    ) -> str | None:
        """
        Récupère une traduction spécifique depuis un fichier de cache.

        Args:
            line_index: Index de la ligne (sous forme de string)

        Returns:
            Le texte traduit si trouvé, None sinon
        """
        file_key = self.cache_dir / self._get_cache_file_name(file_name)
        if file_key not in _data_cache:
            _data_cache[file_key] = _load_cache(file_key)
        data = _data_cache[file_key].get(line_index)
        if data is None and use_fallback and self._fallback is not None:
            return self._fallback._get(file_name, line_index, use_fallback=True)
        return data

    def _get_all(
        self, file_name: Path | str, line_indices: list[str], use_fallback: bool
    ) -> dict[str, str | None]:
        """
        Récupère plusieurs traductions depuis un fichier de cache.

        Args:
            cache_file: Chemin du fichier de cache
            line_indices: Liste d'index de lignes (sous forme de string)

        Returns:
            Dictionnaire {line_index: texte_traduit ou None}
        """
        file_key = self._key_cache / self._get_cache_file_name(file_name)
        missing_indices: list[str] | None = None
        results: dict[str, str | None] = {}
        has_fallback = use_fallback and self._fallback is not None
        if file_key not in _data_cache:
            _data_cache[file_key] = _load_cache(file_key)

        data = _data_cache[file_key]
        for idx in line_indices:
            if idx in data:
                results[idx] = data[idx]
            elif has_fallback:
                missing_indices = (
                    [idx] if missing_indices is None else missing_indices.append(idx)
                )
            else:
                results[idx] = None

        if missing_indices and self._fallback is not None:
            fallback_results = self._fallback._get_all(
                file_name, missing_indices, use_fallback=True
            )
            results.update(fallback_results)
        return results

    def set_fallback(self, fallback_store: Store) -> None:
        """
        Définit un store de fallback pour les recherches de traductions.

        Si une traduction n'est pas trouvée dans ce store, la recherche
        se fera dans le store de fallback (ex: phase précédente).

        Args:
            fallback_store: Instance de Store à utiliser comme fallback

        Example:
            >>> previous_store = Store(Path("cache/previous"))
            >>> current_store = Store(Path("cache/current"))
            >>> current_store.set_fallback(previous_store)
        """
        self._fallback = fallback_store

    def save(
        self,
        source_file: str,
        line_index: str,
        translated_text: str,
    ) -> None:
        """
        Sauvegarde une traduction sur disque.

        Args:
            source_file: Chemin du fichier source
            line_index: Index de la ligne (TagKey.index)
            translated_text: Texte traduit

        Example:
            >>> store = Store()
            >>> store.save("file.html", 0, "Bonjour")
        """
        cache_file: Path = self._get_cache_file_name(source_file)
        data = _load_cache(cache_file)
        data[line_index] = translated_text
        _save_cache(cache_file, data)

    def save_all(self, source_file: str, translations_dict: dict[str, str]) -> None:
        """
        Sauvegarde plusieurs traductions sur disque en une seule opération.

        Args:
            source_file: Chemin du fichier source
            translations_dict: Dictionnaire {line_index: texte_traduit}

        Example:
            >>> store = Store()
            >>> store.save_all("file.html", {0: "Bonjour", 1: "Monde"})
        """
        cache_file = self._get_cache_file_name(source_file)
        data = _load_cache(cache_file)
        data.update(translations_dict)
        _save_cache(cache_file, data)

    def get(
        self,
        source_file: str,
        line_index: str,
        use_fallback: bool = True,
    ) -> str | None:
        """
        Récupère une traduction depuis le disque (lent).

        Args:
            source_file: Chemin du fichier source
            line_index: Index de la ligne (TagKey.index)
            use_fallback: Si True et valeur absente, consulte le store fallback

        Returns:
            Le texte traduit si trouvé, None sinon

        Example:
            >>> store = Store()
            >>> translation = store.get("file.html", 0)
            >>> print(translation)  # "Bonjour" ou None
        """
        v = self._get(source_file, line_index, use_fallback)
        _clear_cache()

        return v

    def get_all(
        self,
        source_file: str,
        line_indices: list[str],
        use_fallback: bool = True,
    ) -> dict[str, str | None]:
        """
        Récupère plusieurs traductions depuis le disque.

        Args:
            source_file: Chemin du fichier source
            line_indices: Liste d'index de lignes (TagKey.index)
            use_fallback: Si True et valeur absente, consulte le store fallback

        Returns:
            Dictionnaire {line_index: texte_traduit ou None}

        Example:
            >>> store = Store()
            >>> translations = store.get_all("file.html", [0, 1])
            >>> print(translations)  # {0: "Bonjour", 1: "Monde"}
        """

        result = self._get_all(source_file, line_indices, use_fallback)
        _clear_cache()

        return result

    def get_from_chunk(
        self, chunk: ChunkProtocol, use_fallback: bool = True
    ) -> tuple[dict[int, str], bool]:
        """Récupère les traductions pour tous les textes du body d'un chunk.

        Utilise la méthode `chunk.fetch()` pour parcourir efficacement les fichiers
        et leurs textes associés, en utilisant l'index du TagKey comme clé.

        Args:
            chunk (Chunk): Le chunk contenant les textes à traduire.
            use_fallback: Si True et valeur absente, consulte le store fallback.
                          Passer False pour vérifier uniquement le store courant
                          (ex: cache check de l'executor).

        Returns:
            Tuple[Dict[int, str], bool]: Un tuple contenant:
            - Un dictionnaire `{line_index: texte_traduit ou chaine vide}`.
            - Un booléen indiquant si au moins une traduction est manquante.

        Examples:
            >>> store = Store()
            >>> translations, has_missing = store.get_from_chunk(chunk)
            >>> if has_missing:
            ...     print("Certaines traductions sont manquantes")
        """
        result: dict[int, str] = {}
        has_missing = False

        for index, (html_page, tag_key, _original_text) in enumerate(
            chunk.fetch_body()
        ):
            source_path = html_page.epub_html.file_name

            translated = self._get(source_path, tag_key.index, use_fallback)

            result[index] = translated or ""
            if translated is None:
                has_missing = True
        _clear_cache()

        return result, has_missing

    def get_all_from_chunk(
        self, chunk: Chunk, use_fallback: bool = True
    ) -> tuple[dict[TagKey, str], bool]:
        """
        Récupère toutes les traductions pour les textes d'un chunk (Head + Body + Tail).

        Utilise la méthode chunk.fetch() pour parcourir efficacement les fichiers
        et leurs textes associés, en utilisant l'index du TagKey comme clé.

        Args:
            chunk: Le chunk contenant les textes à traduire
            use_fallback: Si True et valeur absente, consulte le store fallback.
        """
        result: dict[TagKey, str] = {}
        has_missing = False

        for html_page, tag_key, _original_text in chunk.fetch_all():
            source_path = html_page.epub_html.file_name

            translated = self.get(source_path, tag_key.index, use_fallback)

            result[tag_key] = translated or ""
            if translated is None:
                has_missing = True
        _clear_cache()

        return result, has_missing

    def get_from_file(
        self,
        file_name: str,
        use_fallback: bool = True,
    ) -> dict[str, str]:
        """
        Récupère toutes les traductions sauvegardées pour un fichier source.

        Args:
            file_name: Chemin du fichier source
            use_fallback: Si True, merge avec le store fallback (store courant prioritaire)

        Returns:
            Dictionnaire {clé: texte_traduit} où clé peut être str (index) ou (identifiant)

        Example:
            >>> store = Store()
            >>> translations = store.get_from_file("file.html")
            >>> print(translations)  # {"0": "Bonjour", "1": "Monde"}
        """
        data = _load_cache(self._get_cache_file_name(file_name))
        if use_fallback and self._fallback is not None:
            fallback_data = self._fallback.get_from_file(file_name, use_fallback=True)
            return {**fallback_data, **data}

        return data

    def clear(self, source_file: str) -> None:
        """
        Supprime le cache de traduction pour un fichier source spécifique.

        Args:
            source_file: Chemin du fichier source

        Example:
            >>> store = Store()
            >>> store.clear("file.html")
        """
        cache_file = self._get_cache_file_name(source_file)
        if cache_file.exists():
            cache_file.unlink()

    def clear_all(self) -> None:
        """
        Supprime tous les fichiers de cache du répertoire.

        Attention: Cette opération est irréversible.

        Example:
            >>> store = Store()
            >>> store.clear_all()
        """
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
