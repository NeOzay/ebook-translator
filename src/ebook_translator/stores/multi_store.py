"""
Gestionnaire de stores multiples pour le pipeline en 2 phases.

Ce module fournit MultiStore qui gère séparément les traductions initiales
(Phase 1) et les traductions affinées (Phase 2), avec fallback automatique.
"""

from pathlib import Path
from typing import Literal, Optional, TYPE_CHECKING, TypedDict

from ..store import Store

if TYPE_CHECKING:
    from segment import Chunk
    from htmlpage import TagKey

PhaseType = Literal["initial", "refined"]


class MultiStoreStats(TypedDict):
    """
    Statistiques du MultiStore.

    Attributes:
        active_phase: Phase actuellement active ("initial" ou "refined")
        initial_files: Nombre de fichiers dans initial_store
        refined_files: Nombre de fichiers dans refined_store
    """

    active_phase: PhaseType
    initial_files: int
    refined_files: int


class MultiStore:
    """
    Gestionnaire de stores pour traductions initial et refined.

    Cette classe gère deux stores séparés pour les deux phases du pipeline:
    - initial_store: Traductions de la Phase 1 (gros blocs 1500 tokens)
    - refined_store: Traductions de la Phase 2 (petits blocs 300 tokens, affinées)

    Le store actif est déterminé par `active_phase`. Les opérations get()
    utilisent un fallback : refined → initial → None.

    Attributes:
        initial_store: Store pour les traductions initiales (Phase 1)
        refined_store: Store pour les traductions affinées (Phase 2)
        active_phase: Phase active ("initial" ou "refined")

    Example:
        >>> multi_store = MultiStore(Path("cache"))
        >>> # Phase 1
        >>> multi_store.save_initial("file.html", "0", "Initial translation")
        >>> # Phase 2
        >>> multi_store.switch_to_refined()
        >>> multi_store.save_refined("file.html", "0", "Refined translation")
        >>> # Get avec fallback
        >>> text = multi_store.get("file.html", "0")  # "Refined translation"
    """

    def __init__(self, cache_dir: Path):
        """
        Initialise le MultiStore avec deux stores séparés.

        Args:
            cache_dir: Répertoire racine pour les caches
                      - initial/ pour Phase 1
                      - refined/ pour Phase 2
        """
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Créer les deux stores
        self.initial_store = Store(cache_dir / "initial")
        self.refined_store = Store(cache_dir / "refined")

        # Phase active (commence par initial)
        self.active_phase: PhaseType = "initial"

    def get_active_store(self) -> Store:
        """
        Récupère le store actif selon la phase.

        Returns:
            initial_store ou refined_store selon active_phase
        """
        if self.active_phase == "initial":
            return self.initial_store
        else:
            return self.refined_store

    def switch_to_refined(self) -> None:
        """
        Passe en Phase 2 (refined).

        Après cet appel, le store actif devient refined_store.

        Example:
            >>> multi_store.switch_to_refined()
            >>> assert multi_store.active_phase == "refined"
        """
        self.active_phase = "refined"

    def switch_to_initial(self) -> None:
        """
        Revient en Phase 1 (initial).

        Utile pour tests ou re-traduction.

        Example:
            >>> multi_store.switch_to_initial()
            >>> assert multi_store.active_phase == "initial"
        """
        self.active_phase = "initial"

    def get(
        self,
        source_file: str,
        line_index: str,
        phase: Optional[PhaseType] = None,
    ) -> Optional[str]:
        """
        Récupère une traduction avec fallback automatique.

        Stratégie de fallback:
        1. Si phase spécifiée → chercher dans ce store uniquement
        2. Sinon → chercher dans refined, puis initial

        Args:
            source_file: Chemin du fichier source
            line_index: Index de la ligne
            phase: Phase spécifique à interroger (None = fallback)

        Returns:
            Traduction trouvée ou None

        Example:
            >>> # Fallback refined → initial
            >>> text = multi_store.get("file.html", "0")
            >>> # Phase spécifique
            >>> initial_text = multi_store.get("file.html", "0", phase="initial")
        """
        if phase:
            # Phase spécifiée → chercher uniquement là
            if phase == "initial":
                return self.initial_store.get(source_file, line_index)
            else:
                return self.refined_store.get(source_file, line_index)
        else:
            # Fallback: refined → initial
            text = self.refined_store.get(source_file, line_index)
            if text is None:
                text = self.initial_store.get(source_file, line_index)
            return text

    def save_initial(
        self,
        source_file: str,
        line_index: str,
        translated_text: str,
    ) -> None:
        """
        Sauvegarde une traduction initiale (Phase 1).

        Args:
            source_file: Chemin du fichier source
            line_index: Index de la ligne
            translated_text: Traduction initiale
        """
        self.initial_store.save(source_file, line_index, translated_text)

    def save_refined(
        self,
        source_file: str,
        line_index: str,
        translated_text: str,
    ) -> None:
        """
        Sauvegarde une traduction affinée (Phase 2).

        Args:
            source_file: Chemin du fichier source
            line_index: Index de la ligne
            translated_text: Traduction affinée
        """
        self.refined_store.save(source_file, line_index, translated_text)

    def save_all_initial(
        self,
        source_file: str,
        translations_dict: dict[str, str],
    ) -> None:
        """
        Sauvegarde plusieurs traductions initiales (Phase 1).

        Args:
            source_file: Chemin du fichier source
            translations_dict: Dictionnaire {line_index: traduction_initiale}
        """
        self.initial_store.save_all(source_file, translations_dict)

    def save_all_refined(
        self,
        source_file: str,
        translations_dict: dict[str, str],
    ) -> None:
        """
        Sauvegarde plusieurs traductions affinées (Phase 2).

        Args:
            source_file: Chemin du fichier source
            translations_dict: Dictionnaire {line_index: traduction_affinée}
        """
        self.refined_store.save_all(source_file, translations_dict)

    def get_from_chunk(
        self,
        chunk: "Chunk",
        phase: Optional[PhaseType] = None,
    ) -> tuple[dict[int, str], bool]:
        """
        Récupère les traductions pour un chunk avec fallback.

        Args:
            chunk: Le chunk contenant les textes
            phase: Phase spécifique (None = fallback refined → initial)

        Returns:
            Tuple (traductions, has_missing)
            - traductions: Dictionnaire {index: traduction} (ou None si manquant)
            - has_missing: True si au moins une traduction manque

        Example:
            >>> translations, has_missing = multi_store.get_from_chunk(chunk)
            >>> if has_missing:
            ...     # Lancer traduction
        """
        if phase:
            # Phase spécifique
            if phase == "initial":
                return self.initial_store.get_from_chunk(chunk)
            else:
                return self.refined_store.get_from_chunk(chunk)

        # Fallback: essayer refined, puis initial
        translations, has_missing = self.refined_store.get_from_chunk(chunk)

        if has_missing:
            # Compléter avec initial
            initial_translations, _ = self.initial_store.get_from_chunk(chunk)
            merged = {}
            # Fusionner: priorité à refined, fallback sur initial
            for idx in set(translations.keys()) | set(initial_translations.keys()):
                refined_val = translations.get(idx)
                initial_val = initial_translations.get(idx)
                merged[idx] = refined_val if refined_val else initial_val

            # Re-vérifier s'il manque encore quelque chose
            has_missing = any(t for t in merged.values())
            return merged, has_missing

        return translations, has_missing

    def get_all_from_chunk(
        self,
        chunk: "Chunk",
        phase: Optional[PhaseType] = None,
    ) -> tuple[dict["TagKey", str], bool]:
        if phase:
            # Phase spécifique
            if phase == "initial":
                return self.initial_store.get_all_from_chunk(chunk)
            else:
                return self.refined_store.get_all_from_chunk(chunk)

        # Fallback: essayer refined, puis initial
        translations, has_missing = self.refined_store.get_all_from_chunk(chunk)

        if has_missing:
            # Compléter avec initial
            initial_translations, _ = self.initial_store.get_all_from_chunk(chunk)
            merged: dict[TagKey, str] = {}
            # Fusionner: priorité à refined, fallback sur initial
            for idx in set(translations.keys()) | set(initial_translations.keys()):
                refined_val = translations.get(idx)
                initial_val = initial_translations.get(idx, "")
                merged[idx] = refined_val if refined_val else initial_val

            # Re-vérifier s'il manque encore quelque chose
            has_missing = any(not t for t in merged.values())
            return merged, has_missing

        return translations, has_missing

    def clear_all(self) -> None:
        """
        Supprime tous les caches (initial et refined).

        Attention: Opération irréversible.

        Example:
            >>> multi_store.clear_all()
        """
        self.initial_store.clear_all()
        self.refined_store.clear_all()

    def get_statistics(self) -> MultiStoreStats:
        """
        Récupère des statistiques sur les stores.

        Returns:
            Dictionnaire avec counts pour initial et refined

        Example:
            >>> stats = multi_store.get_statistics()
            >>> print(f"Initial: {stats['initial_files']}, Refined: {stats['refined_files']}")
        """
        initial_files = len(list(self.initial_store.cache_dir.glob("*.json")))
        refined_files = len(list(self.refined_store.cache_dir.glob("*.json")))

        return {
            "active_phase": self.active_phase,
            "initial_files": initial_files,
            "refined_files": refined_files,
        }

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        stats = self.get_statistics()
        return (
            f"MultiStore(\n"
            f"  active_phase={stats['active_phase']},\n"
            f"  initial_files={stats['initial_files']},\n"
            f"  refined_files={stats['refined_files']}\n"
            f")"
        )
