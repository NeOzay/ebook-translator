"""
Store pour sauvegarder et récupérer les traductions sur disque.

Ce module fournit une classe Store pour gérer la persistance des traductions
d'ebooks. Les traductions sont stockées au format JSON avec le numéro de ligne
(index) comme clé et le texte traduit comme valeur.

Format de stockage:
    Nouveau format (v2): {"version": 2, "translations": {int: str}}
    Ancien format (v1): {str: str} - converti automatiquement en v2 lors du chargement

Rétrocompatibilité:
    Les fichiers v1 sont chargés et les traductions sont retrouvées via le texte original.
    Lors de la première écriture, le fichier est migré vers v2.
"""

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .segment import Chunk
    from .htmlpage.tag_key import TagKey


class Store:
    """
    Gestionnaire de persistance pour les traductions d'ebooks.

    Les traductions sont sauvegardées au format JSON avec le texte original
    comme clé et le texte traduit comme valeur. Le nom du fichier de cache
    est dérivé du chemin du fichier source pour faciliter l'identification.

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

    def _load_cache(self, cache_file: Path) -> tuple[dict[int, str], dict[str, str]]:
        """
        Charge un fichier de cache JSON.

        Supporte à la fois le nouveau format (v2) avec numéros de ligne
        et l'ancien format (v1) avec textes originaux comme clés.

        Args:
            cache_file: Chemin du fichier de cache

        Returns:
            Tuple contenant:
            - Dictionnaire des traductions par index {line_index: texte_traduit}
            - Dictionnaire des traductions par texte {texte_original: texte_traduit}
              (utilisé comme fallback pour l'ancien format v1)
        """
        if not cache_file.exists():
            return {}, {}

        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Détection du format
        if isinstance(data, dict):
            # Nouveau format v2: {"version": 2, "translations": {int: str}}
            if "version" in data and data.get("version") == 2:
                # Convertir les clés de string à int (JSON sérialise les int en string)
                by_index = {int(k): v for k, v in data["translations"].items()}
                # Aussi charger le fallback si présent
                by_text = data.get("text_fallback", {})
                return by_index, by_text
            # Ancien format v1: {str: str}
            else:
                # Garder les traductions par texte pour rétrocompatibilité
                return {}, data

        return {}, {}

    def _save_cache(
        self,
        cache_file: Path,
        translations_by_index: dict[int, str],
        translations_by_text: dict[str, str]
    ) -> None:
        """
        Sauvegarde les traductions dans un fichier de cache JSON au format v2.

        Args:
            cache_file: Chemin du fichier de cache
            translations_by_index: Dictionnaire {index: texte_traduit}
            translations_by_text: Dictionnaire {texte_original: texte_traduit} (fallback)
        """
        data = {
            "version": 2,
            "translations": {str(k): v for k, v in translations_by_index.items()},
            "text_fallback": translations_by_text
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save(
        self,
        source_file: str,
        line_index: int,
        translated_text: str,
        original_text: Optional[str] = None
    ) -> None:
        """
        Sauvegarde une traduction sur disque.

        Args:
            source_file: Chemin du fichier source
            line_index: Index de la ligne (TagKey.index)
            translated_text: Texte traduit
            original_text: Texte original (optionnel, pour le fallback v1)

        Example:
            >>> store = Store()
            >>> store.save("file.html", 0, "Bonjour", "Hello")
        """
        cache_file = self._get_cache_file(source_file)
        by_index, by_text = self._load_cache(cache_file)
        by_index[line_index] = translated_text
        if original_text:
            by_text[original_text] = translated_text
        self._save_cache(cache_file, by_index, by_text)

    def save_all(
        self,
        source_file: str,
        translations_dict: dict[int, str],
        text_mapping: Optional[dict[int, str]] = None
    ) -> None:
        """
        Sauvegarde plusieurs traductions sur disque en une seule opération.

        Args:
            source_file: Chemin du fichier source
            translations_dict: Dictionnaire {line_index: texte_traduit}
            text_mapping: Dictionnaire optionnel {line_index: texte_original}
                         pour maintenir le fallback v1

        Example:
            >>> store = Store()
            >>> store.save_all("file.html", {0: "Bonjour", 1: "Monde"})
        """
        cache_file = self._get_cache_file(source_file)
        by_index, by_text = self._load_cache(cache_file)
        by_index.update(translations_dict)

        # Mettre à jour le fallback texte si fourni
        if text_mapping:
            for line_idx, original_text in text_mapping.items():
                if line_idx in translations_dict:
                    by_text[original_text] = translations_dict[line_idx]

        self._save_cache(cache_file, by_index, by_text)

    def get(
        self,
        source_file: str,
        line_index: int,
        original_text: Optional[str] = None
    ) -> Optional[str]:
        """
        Récupère une traduction depuis le disque.

        Essaie d'abord de trouver par index, puis par texte original si fourni
        (pour rétrocompatibilité avec l'ancien format).

        Args:
            source_file: Chemin du fichier source
            line_index: Index de la ligne (TagKey.index)
            original_text: Texte original (optionnel, pour fallback v1)

        Returns:
            Le texte traduit si trouvé, None sinon

        Example:
            >>> store = Store()
            >>> translation = store.get("file.html", 0, "Hello")
            >>> print(translation)  # "Bonjour" ou None
        """
        cache_file = self._get_cache_file(source_file)
        by_index, by_text = self._load_cache(cache_file)

        # Essayer d'abord par index
        result = by_index.get(line_index)
        if result is not None:
            return result

        # Fallback sur le texte original si fourni
        if original_text:
            return by_text.get(original_text)

        return None

    def get_all(
        self,
        source_file: str,
        line_indices: list[int],
        text_mapping: Optional[dict[int, str]] = None
    ) -> dict[int, Optional[str]]:
        """
        Récupère plusieurs traductions depuis le disque.

        Args:
            source_file: Chemin du fichier source
            line_indices: Liste d'index de lignes (TagKey.index)
            text_mapping: Dictionnaire optionnel {line_index: texte_original}
                         pour fallback v1

        Returns:
            Dictionnaire {line_index: texte_traduit ou None}

        Example:
            >>> store = Store()
            >>> translations = store.get_all("file.html", [0, 1])
            >>> print(translations)  # {0: "Bonjour", 1: "Monde"}
        """
        cache_file = self._get_cache_file(source_file)
        by_index, by_text = self._load_cache(cache_file)

        result: dict[int, Optional[str]] = {}
        for idx in line_indices:
            # Essayer d'abord par index
            translated = by_index.get(idx)
            if translated is None and text_mapping and idx in text_mapping:
                # Fallback sur le texte original
                translated = by_text.get(text_mapping[idx])
            result[idx] = translated

        return result

    def get_from_chunk(self, chunk: "Chunk") -> tuple[dict[int, Optional[str]], bool]:
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
        result: dict[int, Optional[str]] = {}
        has_missing = False

        # Cache des traductions par fichier pour éviter les rechargements
        # Stocke un tuple (by_index, by_text) pour chaque fichier
        file_cache: dict[str, tuple[dict[int, str], dict[str, str]]] = {}

        for html_page, tag_key, original_text in chunk.fetch():
            source_path = html_page.epub_html.file_name

            # Charger les traductions du fichier si pas encore en cache
            if source_path not in file_cache:
                file_cache[source_path] = self._load_translations_for_file(html_page)

            by_index, by_text = file_cache[source_path]

            # Utiliser l'index du TagKey comme clé
            line_index = tag_key.index

            # Éviter les doublons (même si peu probable avec les index)
            if line_index not in result:
                # Essayer d'abord par index
                translated = by_index.get(line_index)

                # Fallback sur le texte original (pour rétrocompatibilité v1)
                if translated is None:
                    translated = by_text.get(original_text)

                result[line_index] = translated

                if translated is None:
                    has_missing = True

        return result, has_missing

    def _load_translations_for_file(
        self, html_page
    ) -> tuple[dict[int, str], dict[str, str]]:
        """
        Charge les traductions depuis le cache pour un fichier HTML donné.

        Args:
            html_page: L'objet HtmlPage contenant le fichier source

        Returns:
            Tuple contenant:
            - Dictionnaire {line_index: texte_traduit}
            - Dictionnaire {texte_original: texte_traduit} (fallback v1)
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
