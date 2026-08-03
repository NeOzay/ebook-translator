"""Taxonomie d'erreurs indépendante du SDK d'un provider.

`LLM.query` pilote son backoff sur les exceptions du SDK `openai`. Les providers
bâtis sur un autre SDK traduisent leurs erreurs réseau vers ces classes pour
bénéficier du même traitement (retry, backoff exponentiel, journalisation).
"""


class LLMClientError(Exception):
    """Racine des erreurs réseau normalisées d'un client LLM."""


class LLMTimeoutError(LLMClientError):
    """La requête a expiré avant d'obtenir une réponse."""


class LLMRateLimitError(LLMClientError):
    """Le provider a rejeté la requête pour cause de limite de débit."""


class LLMAPIError(LLMClientError):
    """Erreur renvoyée par l'API du provider (statut HTTP non 2xx, réponse invalide)."""
