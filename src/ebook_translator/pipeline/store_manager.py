"""
Gestionnaire de stores pour les phases.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from ebook_translator.stores.store import Store
from ebook_translator.segmentation.segmentator import Chunk

if TYPE_CHECKING:
    from ebook_translator.pipeline.base import PhaseBase


class StoreManager:
    """
    Gère les stores de toutes les phases.

    Chaque phase a son propre store dans cache/{phase_name}/.
    Une phase peut lire depuis les stores des phases précédentes.

    Example:
        manager = StoreManager(Path("cache"), [InitialPhase, RefinedPhase])

        # Accéder au store d'une phase
        initial_store = manager.get_store("initial")

        # Lire depuis une phase
        translation = manager.get("initial", chunk)

        # Lire avec fallback (refined → initial → None)
        translation = manager.get_with_fallback(chunk, ["refined", "initial"])
    """

    def __init__(self, cache_dir: Path, phases: list[type["PhaseBase"]]):
        """
        Initialise le gestionnaire de stores.

        Args:
            cache_dir: Répertoire racine du cache
            phases: Liste des classes de phases (pour créer les stores)
        """
        self.cache_dir = cache_dir
        self._stores: dict[str, Store] = {}

        # Créer un store par phase
        for phase_class in phases:
            phase_name = phase_class.name
            store_path = cache_dir / phase_name
            store_path.mkdir(parents=True, exist_ok=True)
            self._stores[phase_name] = Store(store_path)

    def get_store(self, phase_name: str) -> Store:
        """
        Récupère le store d'une phase.

        Args:
            phase_name: Nom de la phase (ex: 'initial', 'refined')

        Returns:
            Instance Store pour cette phase

        Raises:
            KeyError: Si la phase n'existe pas
        """
        if phase_name not in self._stores:
            raise KeyError(
                f"Store for phase '{phase_name}' not found. "
                f"Available phases: {list(self._stores.keys())}"
            )
        return self._stores[phase_name]

    def get_translate(self, phase_name: str, chunk: Chunk) -> dict[int, str] | None:
        """
        Helper: lit la traduction d'un chunk depuis le store d'une phase.

        Args:
            phase_name: Nom de la phase
            chunk: Chunk dont on veut la traduction

        Returns:
            Mapping line_index -> translated_text, ou None si pas trouvé
        """
        try:
            store = self.get_store(phase_name)
            result: dict[int, str] = {}

            # Itérer sur chaque ligne du body du chunk
            for line_index, tag_key in enumerate(chunk.body.keys()):
                source_file = tag_key.page.epub_html.file_name
                translated = store.get(source_file, tag_key.index)
                if translated is not None:
                    result[line_index] = translated

            # Retourner None si aucune traduction trouvée
            return result if result else None
        except KeyError:
            return None

    def get_with_fallback(
        self,
        chunk: Chunk,
        phase_order: list[str],
    ) -> dict[int, str] | None:
        """
        Lit avec fallback depuis plusieurs phases.

        Essaie de lire depuis la première phase, puis la seconde, etc.
        jusqu'à trouver une traduction ou épuiser la liste.

        Args:
            chunk: Chunk dont on veut la traduction
            phase_order: Liste des phases dans l'ordre de priorité
                        (ex: ['refined', 'initial'] = refined d'abord, sinon initial)

        Returns:
            Mapping line_index -> translated_text, ou None si pas trouvé

        Example:
            # Lors de la reconstruction EPUB, essayer refined puis initial
            translation = manager.get_with_fallback(chunk, ["refined", "initial"])
        """
        for phase_name in phase_order:
            result = self.get_translate(phase_name, chunk)
            if result is not None:
                return result
        return None

    def has_phase(self, phase_name: str) -> bool:
        """
        Vérifie si un store existe pour cette phase.

        Args:
            phase_name: Nom de la phase

        Returns:
            True si le store existe
        """
        return phase_name in self._stores

    def list_phases(self) -> list[str]:
        """
        Liste les noms de toutes les phases disponibles.

        Returns:
            Liste des noms de phases
        """
        return list(self._stores.keys())

    def clear_phase(self, phase_name: str) -> None:
        """
        Vide le store d'une phase.

        Args:
            phase_name: Nom de la phase à vider

        Raises:
            KeyError: Si la phase n'existe pas
        """
        store = self.get_store(phase_name)

        # Vider tous les fichiers du cache de ce store
        import shutil

        if store.cache_dir.exists():
            shutil.rmtree(store.cache_dir)
            store.cache_dir.mkdir(parents=True, exist_ok=True)

    def __repr__(self) -> str:
        return f"StoreManager(cache_dir={self.cache_dir}, phases={list(self._stores.keys())})"
