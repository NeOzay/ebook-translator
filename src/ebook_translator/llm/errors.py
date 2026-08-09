"""Taxonomie d'erreurs indépendante du SDK d'un provider.

`LLM.query` pilote son backoff sur les exceptions du SDK `openai`. Les providers
bâtis sur un autre SDK traduisent leurs erreurs réseau vers ces classes pour
bénéficier du même traitement (retry, backoff exponentiel, journalisation).
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

RETRY_AFTER_HEADER = "retry-after"
"""En-tête HTTP par lequel un provider annonce le délai avant nouvelle tentative."""


class LLMClientError(Exception):
    """Racine des erreurs réseau normalisées d'un client LLM."""


class LLMTimeoutError(LLMClientError):
    """La requête a expiré avant d'obtenir une réponse."""


class LLMRateLimitError(LLMClientError):
    """Le provider a rejeté la requête pour cause de limite de débit.

    Attributes:
        retry_after: Délai annoncé par le provider en secondes, `None` s'il ne
            l'a pas fourni. Un backoff aveugle ne peut pas deviner une fenêtre
            exprimée par minute : quand cette valeur existe, elle prime.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        """Construit l'erreur en conservant le délai annoncé.

        Args:
            message: Message d'origine du provider.
            retry_after: Délai en secondes extrait des en-têtes, si présent.
        """
        super().__init__(message)
        self.retry_after: float | None = retry_after


class LLMAPIError(LLMClientError):
    """Erreur renvoyée par l'API du provider (statut HTTP non 2xx, réponse invalide)."""


def retry_after_seconds(
    headers: Mapping[str, str] | None,
    now: datetime | None = None,
) -> float | None:
    """Extrait le délai d'attente annoncé par un provider.

    La RFC 9110 autorise deux formes pour `Retry-After` : un nombre de secondes
    (`120`) ou une date HTTP (`Wed, 21 Oct 2015 07:28:00 GMT`). Les deux SDK
    utilisés exposent des `httpx.Headers`, qui satisfont `Mapping[str, str]` et
    dont la recherche est déjà insensible à la casse — un `Mapping` ordinaire
    est accepté pour les tests, la clé étant alors cherchée en minuscules.

    Args:
        headers: En-têtes de la réponse, ou `None` s'ils sont indisponibles.
        now: Instant de référence pour la forme datée (par défaut, maintenant).

    Returns:
        Le délai en secondes, jamais négatif, ou `None` si l'en-tête est absent
        ou illisible.

    Example:
        >>> retry_after_seconds({"retry-after": "30"})
        30.0
        >>> retry_after_seconds({}) is None
        True
    """
    if headers is None:
        return None

    raw = headers.get(RETRY_AFTER_HEADER)
    if raw is None:
        # Un `Mapping` ordinaire n'a pas la recherche insensible à la casse des
        # `httpx.Headers` : on retente sur la forme canonique de la RFC.
        raw = headers.get("Retry-After")
    if raw is None:
        return None

    value = raw.strip()
    if not value:
        return None

    try:
        return max(0.0, float(value))
    except ValueError:
        pass

    try:
        deadline = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None

    # Une date HTTP sans fuseau est réputée UTC ; sans cette normalisation, la
    # soustraction lèverait sur des instants naïf/aware mélangés.
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)

    return max(0.0, (deadline - reference).total_seconds())
