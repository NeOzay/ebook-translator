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

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Optional, cast

if TYPE_CHECKING:
    from .segment import Chunk
    from .htmlpage.tag_key import TagKey


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

    def __init__(self, cache_dir: str = ".translation_cache") -> None:
        """
        Initialise le store avec un répertoire de cache.

        Args:
            cache_dir: Répertoire où sauvegarder les fichiers de traduction.
                      Créé automatiquement s'il n'existe pas.
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

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

    def _load_cache(self, cache_file: Path) -> dict[str, str]:
        """
        Charge un fichier de cache JSON.

        Le cache contient un dictionnaire plat où les clés peuvent être :
        - Des index de ligne (sérialisés en string par JSON) : "0", "1", "2"...
        - Des textes originaux (pour fallback) : "Hello world", "Goodbye"...

        Args:
            cache_file: Chemin du fichier de cache

        Returns:
            Dictionnaire {clé: texte_traduit} où clé peut être int ou str
            Retourne un dictionnaire vide si le fichier n'existe pas
        """
        if not cache_file.exists():
            return {}

        with open(cache_file, "r", encoding="utf-8") as f:
            data: dict[str, str] = json.load(f)
            return data

    def _save_cache(
        self, cache_file: Path, translations_by_index: dict[str, str]
    ) -> None:
        """
        Sauvegarde les traductions dans un fichier de cache JSON.

        Les clés int sont converties en string par la sérialisation JSON.
        Format de sortie : {"0": "Bonjour", "1": "Monde", ...}

        Args:
            cache_file: Chemin du fichier de cache
            translations_by_index: Dictionnaire {index: texte_traduit}
        """
        data = dict(
            sorted(
                translations_by_index.items(),
                key=lambda item: int(item[0]) if item[0].isdigit() else item[0],
            )
        )
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

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
        cache_file = self._get_cache_file(source_file)
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
    ) -> Optional[str]:
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
        return data.get(line_index)

    def get_all(
        self,
        source_file: str,
        line_indices: list[str],
    ) -> dict[str, Optional[str]]:
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

        result: dict[str, Optional[str]] = {}
        for idx in line_indices:
            result[idx] = data.get(idx)

        return result

    def get_from_chunk(self, chunk: "Chunk") -> tuple[list[str], bool]:
        """
        Récupère les traductions pour tous les textes du body d'un chunk.

        Utilise la méthode chunk.fetch() pour parcourir efficacement les fichiers
        et leurs textes associés, en utilisant l'index du TagKey comme clé.
        Fallback sur le texte original pour la rétrocompatibilité v1.

        Args:
            chunk: Le chunk contenant les textes à traduire

        Returns:
            Tuple contenant:
            - Dictionnaire {line_index: texte_traduit ou None}
            - Boolean indiquant si au moins une traduction est manquante

        Example:
            >>> store = Store()
            >>> translations, has_missing = store.get_from_chunk(chunk)
            >>> if has_missing:
            ...     print("Certaines traductions sont manquantes")
        """
        result: list[str] = []
        has_missing = False

        # Cache des traductions par fichier pour éviter les rechargements
        # Stocke le dictionnaire de traductions pour chaque fichier source
        file_cache: dict[str, dict[str, str]] = {}

        for html_page, tag_key, original_text in chunk.fetch():
            source_path = html_page.epub_html.file_name

            # Charger les traductions du fichier si pas encore en cache
            if source_path not in file_cache:
                file_cache[source_path] = self._load_translations_for_file(html_page)

            data = file_cache[source_path]
            # Essayer d'abord par index, puis par texte original (fallback)
            translated = data.get(tag_key.index) or data.get(original_text)

            result.append(translated or original_text)
            if translated is None:
                has_missing = True

        return result, has_missing

    def _load_translations_for_file(self, html_page) -> dict[str, str]:
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
