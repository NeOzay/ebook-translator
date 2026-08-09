"""Limiteur de débit partagé entre les threads **et** entre les processus.

Le pipeline émet ses appels LLM depuis deux familles de threads simultanées —
ceux de `PhaseExecutor` en mode parallèle et ceux du pool de validation — et le
banc d'essais exécute chaque variante dans son propre sous-processus. Un
limiteur en mémoire ne verrait ni les uns ni les autres correctement : il faut
donc superposer deux verrous, et partager l'état par un fichier.

Trois choix structurent ce module :

- **Réservation d'instant, pas accumulation de jetons.** Un « token bucket »
  qui accumule relâche d'un coup tous les threads en attente à la recharge, et
  reproduit exactement la rafale qu'on cherche à éviter. Ici, chaque appelant
  réserve l'instant de *son* départ, et ces instants sont espacés par
  construction.
- **`threading.Lock` et `fcntl.flock`.** Chaque réservation ouvre son propre
  descripteur, donc `flock` sérialise déjà les threads d'un même processus
  aussi bien que les processus — vérifié par mutation : le test d'espacement
  entre threads passe sans le `Lock`. Celui-ci n'est donc pas ce qui espace en
  fonctionnement nominal ; il protège l'état mutable partagé (`_rate`,
  `_successes`, `_local_deadline`) et porte l'espacement en mode dégradé, quand
  le fichier est indisponible ou `fcntl` absent.
- **Le sommeil a lieu verrous relâchés.** Dormir sous verrou sérialiserait les
  appelants au lieu de les espacer : le débit s'effondrerait au lieu d'être
  plafonné.

Le débit s'auto-ajuste (AIMD) : un 429 divise le débit autorisé par deux, une
série de succès le remonte par paliers vers le débit nominal. La pénalité est
en outre reportée dans le fichier partagé, donc un 429 subi par un thread
protège aussi les autres threads et les autres processus.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import IO, final

from ..logger import get_logger

logger = get_logger(__name__)

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - plateformes non-Unix
    _fcntl = None

HAS_FLOCK = _fcntl is not None
"""Faux hors Unix : le débit n'est alors plafonné qu'au sein du processus."""

DEFAULT_STATE_SUBDIR = "ebook-translator/rate"
"""Sous-répertoire du cache utilisateur où vivent les fichiers de créneau."""

PENALTY_DIVISOR = 2.0
"""Facteur de division du débit à chaque 429 (le « MD » d'AIMD)."""

RECOVERY_RATIO = 0.1
"""Fraction du débit nominal regagnée par palier de récupération (le « AI »)."""

RECOVERY_STREAK = 10
"""Nombre de succès consécutifs ouvrant un palier de récupération."""

MAX_DEGRADATION = 64.0
"""Plancher du débit dégradé, en fraction du nominal : jamais moins de 1/64."""


def default_state_dir() -> Path:
    """Répertoire des fichiers de créneau, hors de tout run.

    Le plafond protège un compte d'API, pas un run : deux bancs lancés en
    parallèle, ou un pipeline lancé à côté d'un banc, doivent se partager le
    même créneau. L'emplacement est donc global à l'utilisateur.

    Returns:
        `$XDG_CACHE_HOME/ebook-translator/rate`, ou son équivalent sous
        `~/.cache` si la variable n'est pas définie.
    """
    root = os.environ.get("XDG_CACHE_HOME")
    base = Path(root) if root else Path.home() / ".cache"
    return base / DEFAULT_STATE_SUBDIR


def provider_key_for(client: object) -> str:
    """Clé de partage du créneau pour un client LLM.

    Le protocole `ClientProviderProtocol` n'impose pas l'attribut : un client
    tiers, ou un double de test, reste utilisable et retombe sur son nom de
    classe — `Deepseek` donne `deepseek`, ce qui suffit à séparer les providers.

    Args:
        client: Instance de client LLM.

    Returns:
        La clé déclarée par le client, ou son nom de classe à défaut.

    Example:
        >>> class Deepseek: ...
        >>> provider_key_for(Deepseek())
        'Deepseek'
    """
    declared = getattr(client, "provider_key", None)
    if isinstance(declared, str) and declared:
        return declared
    return type(client).__name__


def _sanitize(provider_key: str) -> str:
    """Réduit une clé de provider à un nom de fichier sûr.

    Args:
        provider_key: Clé déclarée par le client LLM.

    Returns:
        La clé filtrée, jamais vide.
    """
    cleaned = "".join(c if c.isalnum() or c in "-_" else "_" for c in provider_key)
    return cleaned.lower() or "default"


@final
class RateLimiter:
    """Espace les appels LLM d'un provider, tous threads et processus confondus.

    Attributes:
        provider_key: Clé identifiant le provider ; deux limiteurs qui la
            partagent partagent leur créneau.
        state_path: Fichier portant l'instant du prochain départ autorisé.

    Example:
        >>> limiter = RateLimiter(per_minute=60, provider_key="demo")
        >>> limiter.acquire()  # premier appel : immédiat
    """

    def __init__(
        self,
        per_minute: float,
        provider_key: str,
        state_dir: Path | None = None,
    ) -> None:
        """Construit un limiteur pour un provider donné.

        Args:
            per_minute: Nombre maximal d'appels par minute. Accepte un flottant :
                les quotas se lisent souvent en requêtes par seconde, et un
                arrondi à l'entier fausserait le plafond — Mistral
                `mistral-large-2512` annonce 0,07 req/s, soit 4,2 par minute.
            provider_key: Clé du provider, utilisée comme nom de fichier.
            state_dir: Répertoire du fichier de créneau (défaut :
                `default_state_dir()`). Surchargé par les tests.

        Raises:
            ValueError: Si `per_minute` est nul ou négatif — un plafond mal
                réglé doit se voir, pas passer silencieusement en illimité.
        """
        if per_minute <= 0:
            raise ValueError(
                f"per_minute doit être strictement positif, reçu {per_minute}. "
                f"Pour ne pas limiter le débit, ne configurez pas de limiteur."
            )

        self.provider_key: str = _sanitize(provider_key)
        self._nominal_rate: float = per_minute / 60.0
        self._min_rate: float = self._nominal_rate / MAX_DEGRADATION
        self._rate: float = self._nominal_rate

        self._thread_lock: threading.Lock = threading.Lock()
        self._successes: int = 0
        self._local_deadline: float = 0.0

        directory = state_dir if state_dir is not None else default_state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        self.state_path: Path = directory / self.provider_key

        if not HAS_FLOCK:  # pragma: no cover - plateformes non-Unix
            logger.warning(
                "fcntl indisponible : le débit n'est plafonné qu'au sein de ce "
                "processus. Les sous-processus de banc ne partageront pas leur "
                "créneau."
            )

    @property
    def interval(self) -> float:
        """Espacement courant entre deux départs, en secondes."""
        with self._thread_lock:
            return 1.0 / self._rate

    @property
    def current_rate(self) -> float:
        """Débit autorisé courant, en appels par seconde."""
        with self._thread_lock:
            return self._rate

    def acquire(self) -> None:
        """Réserve le prochain créneau et attend qu'il soit venu.

        Bloque l'appelant jusqu'à l'instant réservé. La réservation est faite
        sous les deux verrous ; l'attente, elle, a lieu une fois les verrous
        relâchés, sans quoi les appelants seraient sérialisés au lieu d'être
        espacés.
        """
        with self._thread_lock:
            interval = 1.0 / self._rate
            target = self._reserve(interval)

        delay = target - time.time()
        if delay > 0:
            time.sleep(delay)

    def penalize(self, retry_after: float | None = None) -> float:
        """Réduit le débit après un rejet du provider.

        Args:
            retry_after: Délai annoncé par le provider, s'il l'a fourni. Il sert
                de plancher : le prochain créneau est repoussé d'au moins cette
                durée, pour tous les appelants du même provider.

        Returns:
            La pause effectivement imposée au prochain départ, en secondes.
            L'appelant n'a pas à dormir lui-même : `acquire()` l'attendra. La
            valeur sert à journaliser l'attente réelle et à la décompter d'un
            budget — un appelant qui dormirait en plus attendrait deux fois.
        """
        with self._thread_lock:
            self._successes = 0
            self._rate = max(self._min_rate, self._rate / PENALTY_DIVISOR)
            # Le délai annoncé est un plancher, pas un remplacement : si le
            # nouvel intervalle est plus long, c'est lui qui protège.
            pause = max(retry_after or 0.0, 1.0 / self._rate)
            # La pénalité est reportée dans le fichier partagé : sans cela, les
            # autres threads — et les autres processus — repartiraient aussitôt
            # sur l'ancien créneau et reprendraient un 429.
            _ = self._reserve(0.0, extra_pause=pause)
            degraded = self._rate * 60

        logger.warning(
            f"🚦 Débit {self.provider_key} réduit à {degraded:.1f}/min "
            f"(prochain départ dans {pause:.1f}s)"
        )
        return pause

    def record_success(self) -> None:
        """Compte un appel abouti et regagne du débit par paliers."""
        with self._thread_lock:
            if self._rate >= self._nominal_rate:
                self._successes = 0
                return

            self._successes += 1
            if self._successes < RECOVERY_STREAK:
                return

            self._successes = 0
            self._rate = min(
                self._nominal_rate,
                self._rate + self._nominal_rate * RECOVERY_RATIO,
            )
            regained = self._rate * 60

        logger.info(f"🟢 Débit {self.provider_key} remonté à {regained:.1f}/min")

    def _reserve(self, interval: float, extra_pause: float = 0.0) -> float:
        """Réserve l'instant du prochain départ dans le fichier partagé.

        Appelé sous `self._thread_lock`. Prend le verrou inter-processus le
        temps du cycle lecture / écriture, et le relâche avant de rendre la
        main : c'est l'appelant qui attend, pas le détenteur du verrou.

        Args:
            interval: Espacement à réserver après l'instant retenu.
            extra_pause: Délai supplémentaire imposé à tous les appelants, en
                plus de l'espacement (utilisé par `penalize`).

        Returns:
            L'instant, en temps mural, auquel l'appelant peut partir.
        """
        # `time.time()` et non `time.monotonic()` : c'est la seule horloge
        # comparable entre deux processus. Un recalage d'horloge peut donc
        # décaler un créneau — conséquence acceptée, l'alternative n'existe pas
        # pour un état partagé par fichier.
        now = time.time()

        try:
            with self.state_path.open("a+", encoding="utf-8") as handle:
                self._lock_file(handle)
                try:
                    shared = self._read_deadline(handle)
                    target = max(shared, self._local_deadline, now) + extra_pause
                    self._write_deadline(handle, target + interval)
                finally:
                    self._unlock_file(handle)
        except OSError as error:
            # Un cache indisponible ne doit pas faire échouer une traduction :
            # on retombe sur l'échéance locale, qui espace toujours les
            # appelants de ce processus — sans elle, la panne du fichier
            # rendrait le limiteur inopérant au lieu de le dégrader.
            logger.warning(
                f"Créneau partagé indisponible ({error}) : espacement local seul."
            )
            target = max(self._local_deadline, now) + extra_pause

        self._local_deadline = target + interval
        return target

    @staticmethod
    def _read_deadline(handle: IO[str]) -> float:
        """Lit l'instant du prochain départ, 0 si le fichier est neuf ou illisible."""
        _ = handle.seek(0)
        try:
            return float(handle.read().strip() or 0.0)
        except ValueError:
            return 0.0

    @staticmethod
    def _write_deadline(handle: IO[str], deadline: float) -> None:
        """Écrit l'instant du prochain départ, en remplaçant le contenu."""
        _ = handle.seek(0)
        handle.truncate()
        _ = handle.write(f"{deadline:.6f}")
        handle.flush()

    @staticmethod
    def _lock_file(handle: IO[str]) -> None:
        """Prend le verrou exclusif inter-processus, s'il est disponible."""
        if _fcntl is not None:
            _fcntl.flock(handle.fileno(), _fcntl.LOCK_EX)

    @staticmethod
    def _unlock_file(handle: IO[str]) -> None:
        """Relâche le verrou inter-processus."""
        if _fcntl is not None:
            _fcntl.flock(handle.fileno(), _fcntl.LOCK_UN)
