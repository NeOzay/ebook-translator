"""
Worker dédié à la sauvegarde des traductions validées.

Ce module fournit un worker unique qui gère toutes les écritures dans le Store,
offrant les avantages suivants:

1. **Découplage I/O** : La validation (CPU-bound) et la sauvegarde (I/O-bound)
   sont parallélisées, améliorant le throughput de ~33-50%.

2. **Backpressure** : SaveQueue limite l'utilisation mémoire en cas de disque lent.

3. **Ordre déterministe** : Les sauvegardes se font dans l'ordre de validation (FIFO),
   facilitant le débogage et garantissant la cohérence.

4. **Gestion d'erreurs centralisée** : Logs et statistiques cohérents, les erreurs
   d'écriture ne crashent pas les ValidationWorkers.

5. **Callbacks thread-safe** : on_validated exécuté après sauvegarde confirmée,
   éliminant les race conditions dans l'apprentissage du glossaire.

Architecture:
    ValidationWorkers (N threads) → SaveQueue → SaveWorker (1 thread) → Store

Note: Store.py a ses propres verrous par fichier pour gérer la concurrence,
      SaveWorker apporte des bénéfices architecturaux complémentaires.
"""

import queue
import threading
from typing import TYPE_CHECKING, Callable, Optional

from ..logger import get_logger
from .validation_queue import SaveQueue, SaveItem

if TYPE_CHECKING:
    from ..segmentation.segmentator import Chunk
    from ..stores.store import Store

logger = get_logger(__name__)


class SaveWorker:
    """
    Worker dédié à la sauvegarde des traductions validées dans le Store.

    Ce worker consomme la SaveQueue et écrit chaque item dans le Store de manière
    séquentielle. Il fournit un pipeline I/O dédié qui découple la validation
    (CPU-bound) de la persistance (I/O-bound), améliorant les performances globales
    de ~33-50%.

    Bénéfices architecturaux:
        - **Performance**: ValidationWorkers ne bloquent pas sur les écritures disque
        - **Ordre déterministe**: Sauvegardes FIFO dans l'ordre de validation
        - **Callbacks thread-safe**: on_validated exécuté après confirmation de sauvegarde
        - **Gestion d'erreurs centralisée**: Logs cohérents, statistiques unifiées
        - **Backpressure**: SaveQueue limite l'utilisation mémoire

    Attributes:
        save_queue: Queue des items à sauvegarder
        store: Store où écrire les traductions (thread-safe avec verrous par fichier)
        on_validated: Callback optionnel appelé après sauvegarde réussie
        saved_count: Compteur d'items sauvegardés avec succès
        error_count: Compteur d'erreurs de sauvegarde

    Example:
        >>> save_queue = SaveQueue(maxsize=100)
        >>> save_worker = SaveWorker(
        ...     save_queue=save_queue,
        ...     store=store,
        ...     on_validated=lambda chunk, translations: print(f"Saved {chunk.index}")
        ... )
        >>> # Lancer dans un thread
        >>> thread = threading.Thread(target=save_worker.run, daemon=True)
        >>> thread.start()
    """

    def __init__(
        self,
        save_queue: SaveQueue,
        store: "Store",
        on_validated: Optional[Callable[["Chunk", dict[int, str]], None]] = None,
        stop_event: threading.Event | None = None,
    ):
        """
        Initialise le SaveWorker.

        Args:
            save_queue: Queue des items à sauvegarder
            store: Store où écrire les traductions
            on_validated: Callback optionnel appelé après sauvegarde réussie
                         avec (chunk, final_translations). Utile pour apprentissage
                         glossaire depuis traductions validées.
            stop_event: Event partagé pour signal d'arrêt (set() → arrêt immédiat).
                       Si None, crée un Event local (pour compatibilité tests).
        """
        self.save_queue = save_queue
        self.store = store
        self.on_validated = on_validated
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self.saved_count = 0
        self.error_count = 0

    def run(self) -> None:
        """
        Boucle principale du SaveWorker.

        Consomme la save_queue et écrit chaque item dans le Store jusqu'à
        ce que stop_event soit set.

        Cette méthode bloque jusqu'à ce que:
        1. Un SaveItem soit disponible dans la queue → sauvegarde
        2. stop_event.set() → arrêt gracieux

        Note:
            Cette méthode doit être lancée dans un thread séparé.
            Utilise un timeout court (0.5s) pour permettre une réactivité rapide.
            Vérification stop_event à chaque timeout pour arrêt immédiat.
        """
        logger.info("🟢 SaveWorker démarré")

        while not self.stop_event.is_set():
            try:
                # Récupérer prochain item (timeout court pour réactivité)
                item = self.save_queue.get(timeout=0.5)

            except queue.Empty:
                # Timeout - vérifier stop_event et continuer
                continue

            # Si item est None, c'est une erreur (ne devrait plus arriver avec stop_event)
            if item is None:
                logger.warning(
                    "SaveWorker: Reçu None (comportement déprécié, "
                    "utiliser stop_event.set() à la place)"
                )
                continue

            # Sauvegarder l'item
            try:
                self._save_item(item)
            except Exception as e:
                # Logger l'erreur mais NE PAS crasher le worker
                # (un échec de sauvegarde ne doit pas bloquer tout le pipeline)
                logger.error(
                    f"❌ Erreur sauvegarde chunk {item.chunk.index}: {e}",
                    exc_info=True,
                )
                self.save_queue.mark_error()
                self.error_count += 1

        logger.info(
            f"🔴 SaveWorker arrêté "
            f"(sauvegardés: {self.saved_count}, erreurs: {self.error_count})"
        )

    def _save_item(self, item: SaveItem) -> None:
        """
        Sauvegarde un item dans le Store.

        Cette méthode:
        1. Écrit toutes les traductions dans le Store (via store.save_all)
        2. Marque l'item comme sauvegardé dans la SaveQueue
        3. Appelle le callback on_validated si fourni
        4. Incrémente le compteur de sauvegardes

        Args:
            item: L'item à sauvegarder (contient chunk, translations, source_files)

        Raises:
            Exception: Toute erreur de sauvegarde est propagée (loggée par run())

        Note:
            Store.save_all() est thread-safe (verrous par fichier), mais SaveWorker
            fournit un pipeline I/O dédié pour découpler validation et persistance.
        """
        # 1. Écrire dans Store (thread-safe via verrous par fichier)
        for source_file, translations in item.source_files.items():
            self.store.save_all(source_file, translations)

        # 2. Marquer comme sauvegardé
        self.save_queue.mark_saved()
        self.saved_count += 1

        logger.debug(
            f"💾 Chunk {item.chunk.index} sauvegardé "
            f"({len(item.source_files)} fichier(s), {len(item.final_translations)} ligne(s))"
        )

        # 3. Callback optionnel (ex: apprentissage glossaire)
        if self.on_validated:
            try:
                self.on_validated(item.chunk, item.final_translations)
            except Exception as e:
                # Ne pas crasher si le callback échoue
                logger.warning(
                    f"⚠️ Erreur dans callback on_validated pour chunk {item.chunk.index}: {e}"
                )

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        return (
            f"SaveWorker(\n"
            f"  saved={self.saved_count},\n"
            f"  errors={self.error_count},\n"
            f"  queue_pending={self.save_queue.qsize()}\n"
            f")"
        )
