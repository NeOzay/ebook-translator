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

from ..logger import get_logger

if TYPE_CHECKING:
    from ..htmlpage import HtmlPage, TagKey
    from ..segmentation.segmentator import Chunk

logger = get_logger(__name__)


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

    def __init__(self, cache_dir: Path) -> None:
        """
        Initialise le store avec un répertoire de cache.

        Args:
            cache_dir: Répertoire où sauvegarder les fichiers de traduction.
                      Créé automatiquement s'il n'existe pas.
        """
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Protection thread-safe : Lock par fichier de cache
        # Clé = chemin absolu du fichier cache, Valeur = Lock dédié
        self._file_locks: dict[str, threading.Lock] = {}
        self._file_locks_lock = threading.Lock()  # Protéger accès au dict lui-même

    def _get_cache_file(self, source_file: str) -> Path:
        """
        Génère le chemin du fichier de cache basé sur le fichier source.

        Le nom du fichier combine le chemin source (sécurisé pour le système de
        fichiers) et un hash court pour garantir l'unicité.

        Args:
            source_file: Chemin du fichier source

        Returns:
            Path du fichier de cache JSON
        """
        # Convertit le chemin en un nom de fichier sûr
        safe_name = (
            str(Path(source_file)).replace("\\", "_").replace("/", "_").replace(":", "")
        )

        # Hash court pour garantir l'unicité
        file_hash = hashlib.md5(source_file.encode()).hexdigest()[:8]

        return self.cache_dir / f"{safe_name}_{file_hash}.json"

    def _get_file_lock(self, cache_file: Path) -> threading.Lock:
        """
        Récupère ou crée le Lock associé à un fichier de cache.

        Cette méthode garantit qu'un seul Lock existe par fichier de cache,
        permettant une synchronisation thread-safe des opérations lecture/écriture.

        Args:
            cache_file: Chemin du fichier de cache

        Returns:
            Lock dédié à ce fichier de cache

        Note:
            Thread-safe : utilise _file_locks_lock pour protéger l'accès au dictionnaire.
        """
        cache_key = str(cache_file.absolute())

        with self._file_locks_lock:
            if cache_key not in self._file_locks:
                self._file_locks[cache_key] = threading.Lock()
            return self._file_locks[cache_key]

    def _load_cache(self, cache_file: Path) -> dict[str, str]:
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

        file_lock = self._get_file_lock(cache_file)

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
                logger.error(f"⚠️  Erreur lecture cache {cache_file.name}: {e}")
                return {}
            except json.JSONDecodeError as e:
                logger.error(f"⚠️  Cache corrompu {cache_file.name}: {e}")
                # Tenter de sauvegarder une backup avant de retourner un cache vide
                backup_file = cache_file.with_suffix(".json.backup")
                try:
                    cache_file.rename(backup_file)
                    logger.error(f"📦 Backup sauvegardée: {backup_file.name}")
                except Exception:
                    pass
                return {}

    def _save_cache(
        self, cache_file: Path, translations_by_index: dict[str, str]
    ) -> None:
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

        file_lock = self._get_file_lock(cache_file)

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
        cache_file: Path = self._get_cache_file(source_file)
        data = self._load_cache(cache_file)
        data[line_index] = translated_text
        self._save_cache(cache_file, data)

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
        cache_file = self._get_cache_file(source_file)
        data = self._load_cache(cache_file)
        data.update(translations_dict)
        self._save_cache(cache_file, data)

    def get(
        self,
        source_file: str,
        line_index: str,
    ) -> str | None:
        """
        Récupère une traduction depuis le disque.

        Args:
            source_file: Chemin du fichier source
            line_index: Index de la ligne (TagKey.index)

        Returns:
            Le texte traduit si trouvé, None sinon

        Example:
            >>> store = Store()
            >>> translation = store.get("file.html", 0)
            >>> print(translation)  # "Bonjour" ou None
        """
        cache_file = self._get_cache_file(source_file)
        data = self._load_cache(cache_file)

        # Essayer d'abord par index
        return data.get(line_index, None)

    def get_all(
        self,
        source_file: str,
        line_indices: list[str],
    ) -> dict[str, str | None]:
        """
        Récupère plusieurs traductions depuis le disque.

        Args:
            source_file: Chemin du fichier source
            line_indices: Liste d'index de lignes (TagKey.index)

        Returns:
            Dictionnaire {line_index: texte_traduit ou None}

        Example:
            >>> store = Store()
            >>> translations = store.get_all("file.html", [0, 1])
            >>> print(translations)  # {0: "Bonjour", 1: "Monde"}
        """
        cache_file = self._get_cache_file(source_file)
        data = self._load_cache(cache_file)

        result: dict[str, str | None] = {}
        for idx in line_indices:
            result[idx] = data.get(idx)

        return result

    def get_from_chunk(self, chunk: Chunk) -> tuple[dict[int, str], bool]:
        """Récupère les traductions pour tous les textes du body d'un chunk.

        Utilise la méthode `chunk.fetch()` pour parcourir efficacement les fichiers
        et leurs textes associés, en utilisant l'index du TagKey comme clé.

        Args:
            chunk (Chunk): Le chunk contenant les textes à traduire.

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

        # Cache des traductions par fichier pour éviter les rechargements
        # Stocke le dictionnaire de traductions pour chaque fichier source
        file_cache: dict[str, dict[str, str]] = {}

        for index, (html_page, tag_key, _original_text) in enumerate(
            chunk.fetch_body()
        ):
            source_path = html_page.epub_html.file_name

            # Charger les traductions du fichier si pas encore en cache
            if source_path not in file_cache:
                file_cache[source_path] = self._load_translations_for_file(html_page)

            data = file_cache[source_path]
            # Essayer d'abord par index, puis par texte original (fallback)
            translated = data.get(tag_key.index)

            result[index] = translated or ""
            if translated is None:
                has_missing = True

        return result, has_missing

    def get_all_from_chunk(self, chunk: Chunk) -> tuple[dict[TagKey, str], bool]:
        """
        Récupère toutes les traductions pour les textes d'un chunk (Head + Body + Tail).

        Utilise la méthode chunk.fetch() pour parcourir efficacement les fichiers
        et leurs textes associés, en utilisant l'index du TagKey comme clé.

        Args:
            chunk: Le chunk contenant les textes à traduire
        """
        result: dict[TagKey, str] = {}
        has_missing = False

        # Cache des traductions par fichier pour éviter les rechargements
        # Stocke le dictionnaire de traductions pour chaque fichier source
        file_cache: dict[str, dict[str, str]] = {}

        for html_page, tag_key, _original_text in chunk.fetch_all():
            source_path = html_page.epub_html.file_name

            # Charger les traductions du fichier si pas encore en cache
            if source_path not in file_cache:
                file_cache[source_path] = self._load_translations_for_file(html_page)

            data = file_cache[source_path]
            # Essayer d'abord par index, puis par texte original (fallback)
            translated = data.get(tag_key.index)

            result[tag_key] = translated or ""
            if translated is None:
                has_missing = True

        return result, has_missing

    def get_from_file(
        self,
        file_name: str ,
    ) -> dict[str, str]:
        """
        Récupère toutes les traductions pour un fichier HTML donné.

        Args:
            html_page: L'objet HtmlPage contenant le fichier source

        Returns:
            Dictionnaire {clé: texte_traduit} où clé peut être int ou str
            Les clés sont soit des index de ligne, soit un identifiant de texte original
        """
        return self._load_cache(self._get_cache_file(file_name))

    def _load_translations_for_file(self, html_page: HtmlPage) -> dict[str, str]:
        """
        Charge les traductions depuis le cache pour un fichier HTML donné.

        Args:
            html_page: L'objet HtmlPage contenant le fichier source

        Returns:
            Dictionnaire {clé: texte_traduit} où clé peut être int ou str
            Les clés sont soit des index de ligne, soit des textes originaux
        """
        source_file = html_page.epub_html.file_name
        cache_file = self._get_cache_file(source_file)
        return self._load_cache(cache_file)

    def clear(self, source_file: str) -> None:
        """
        Supprime le cache de traduction pour un fichier source spécifique.

        Args:
            source_file: Chemin du fichier source

        Example:
            >>> store = Store()
            >>> store.clear("file.html")
        """
        cache_file = self._get_cache_file(source_file)
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
