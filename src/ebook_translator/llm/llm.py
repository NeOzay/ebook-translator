import datetime
import time
from pathlib import Path
from typing import Any

from openai import APIError, APITimeoutError, OpenAIError, RateLimitError

from ebook_translator.llm.clients.client import ClientProviderProtocol
from ebook_translator.llm.errors import (
    LLMAPIError,
    LLMClientError,
    LLMRateLimitError,
    LLMTimeoutError,
    retry_after_seconds,
)
from ebook_translator.llm.llm_config import (
    LLMConfig,
)
from ebook_translator.llm.rate_limit import RateLimiter
from template.types import ConvertibleModel

from ..logger import get_logger, get_session_log_path
from .logger import LLMLogger
from .template_renderers import DEFAULT_PROMPT_DIR, TemplateRenderer
from .usage import UsageMeter

logger = get_logger(__name__)

MAX_RATE_LIMIT_DELAY = 30.0
"""Plafond d'une attente calculée par backoff, en secondes.

Sans lui, la progression `3**n` consomme le budget en cinq rejets (1, 3, 9, 27,
81) : l'essentiel part en une seule attente démesurée au lieu de financer
plusieurs tentatives espacées. Ne s'applique pas à un délai annoncé par le
provider, qui fait autorité — s'il excède le budget, l'appel abandonne.
"""

MAX_RATE_LIMIT_HITS = 20
"""Rejets de débit tolérés sur un même appel, quel que soit le budget restant.

Garde-fou contre un provider qui annoncerait `Retry-After: 0` en boucle : sans
elle, un délai nul ne consommerait aucun budget et la boucle ne finirait pas.
"""

DEFAULT_RATE_LIMIT_BUDGET = 120.0
"""Secondes d'attente accordées aux 429 sur un même appel.

Ce budget est **distinct** de `max_retries`, qui compte des tentatives réseau.
Les confondre plafonnait l'attente à 4 s au total (`retry_delay * 3**attempt`,
3 tentatives), ce qui ne peut pas franchir une limite exprimée par minute : le
pipeline abandonnait le chunk avant que la fenêtre du provider ne se rouvre.
"""


def _announced_delay(error: Exception) -> float | None:
    """Délai que le provider a annoncé avec son rejet, s'il en a annoncé un.

    Args:
        error: Erreur de limite de débit, normalisée ou issue du SDK openai.

    Returns:
        Le délai en secondes, ou `None` si le provider ne l'a pas fourni.
    """
    if isinstance(error, LLMRateLimitError):
        return error.retry_after

    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    return retry_after_seconds(headers)


# TODO Je trouve que le nom de la classe est mauvais et porte a confusion avec les clients LLM
class LLM:
    """
    Classe synchrone pour gérer un LLM (DeepSeek, GPT, etc.)
    avec :
      - rendu de templates Jinja2,
      - logs créés à l'envoi,
      - callback exécuté à la réception,
      - exécution parallèle avec limite de simultanéité.
    """

    def __init__(
        self,
        # `Any` sur les paramètres du provider : `LLM` ne fait que relayer les
        # configs, il n'a pas à connaître la forme des kwargs d'un provider
        # donné. Sans cela, la contravariance de `U` rejette tout client
        # concret (Deepseek, …) au profit du seul `UserKwargs` de base.
        client: ClientProviderProtocol[Any, Any],
        prompt_dir: str = DEFAULT_PROMPT_DIR,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        glossary_max_terms: int = 25,
        rate_limiter: RateLimiter | None = None,
        rate_limit_budget: float = DEFAULT_RATE_LIMIT_BUDGET,
    ):
        self.client: ClientProviderProtocol[Any, Any] = client
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.rate_limiter: RateLimiter | None = rate_limiter
        self.rate_limit_budget = rate_limit_budget
        self._exchange_counter = 0

        # Comptabilité des tokens : alimentée à chaque réponse aboutie, lue en
        # fin de phase par `PhaseExecutor` pour remplir `PhaseStats`.
        self.usage = UsageMeter()

        self.llm_logger = LLMLogger(logger)

        # Renderer encapsulé pour templates typés (API recommandée)
        self.renderer = TemplateRenderer(prompt_dir, glossary_max_terms)

    # -----------------------------------
    # 🔹 Requête asynchrone simple
    # -----------------------------------
    def query(
        self,
        system_prompt: str,
        content: str,
        log_name: str | None = None,
        config: LLMConfig | ClientProviderProtocol | None = None,
    ) -> str:
        """
        Envoie une requête au LLM avec gestion d'erreurs spécifiques et retry automatique.

        Args:
            system_prompt: Le prompt système définissant le comportement du LLM
            content: Le contenu à traiter
            log_name: Contexte optionnel pour nommer le fichier de log
                    (ex: "chunk_042", "retry_phase1", "validation")
            config: Configuration fournie par l'utilisateur ou exportée, à adapter selon le provider
        Returns:
            La réponse du LLM ou un message d'erreur entre crochets

        Note:
            Les erreurs sont loggées et un fichier de log est créé pour chaque requête.
            Le fichier de log n'est créé qu'au moment où la réponse est disponible.

            Deux politiques de retry cohabitent, volontairement séparées :
            les erreurs réseau consomment `max_retries` tentatives avec backoff
            exponentiel, tandis qu'une limite de débit (429) ne consomme aucune
            tentative mais un budget en secondes (`rate_limit_budget`). Un 429
            attend le délai annoncé par le provider (`Retry-After`) quand il en
            fournit un, sinon un backoff plafonné par `MAX_RATE_LIMIT_DELAY`.

            En mode raisonnement (use_reasoning_mode=True), le modèle deepseek-reasoner
            génère un processus de pensée explicite (reasoning_content) qui est loggé
            séparément pour faciliter le debugging des corrections complexes.

            En mode JSON (use_json_mode=True), le LLM est contraint de retourner du JSON
            valide. Le prompt doit contenir le mot "json" pour que cela fonctionne correctement.
        """
        log_path = self._make_log_path(log_name)
        self.llm_logger.set_exchange_file(log_path)
        last_error: Exception | None = None

        if isinstance(config, ClientProviderProtocol):
            client = config
            config = None
        else:
            client = self.client

        attempt = 0
        rate_limit_spent = 0.0
        rate_limit_hits = 0

        while attempt < self.max_retries:
            self._await_slot()
            try:
                result = client.request(
                    system_prompt=system_prompt,
                    user_instruction=content,
                    config=config,
                    logger=self.llm_logger,
                )

                self.usage.record(result)
                response_text = result.content if result.content else "Result Empty"
                if self.rate_limiter is not None:
                    self.rate_limiter.record_success()

                if attempt > 0:
                    self.llm_logger.info(
                        f"✅ Requête LLM réussie après {attempt + 1} tentative(s) "
                        f"({len(content)} chars)"
                    )
                else:
                    self.llm_logger.info(
                        f"✅ Requête LLM réussie ({len(content)} chars)"
                    )

                return response_text

            # Chaque clause associe l'exception du SDK openai à son équivalent
            # normalisé (`llm/errors.py`), que lèvent les providers bâtis sur un
            # autre SDK — le comportement de retry est ainsi le même pour tous.
            # Un 429 ne consomme pas de tentative réseau : il consomme du temps.
            # Le mélanger à `max_retries` bornait l'attente à quelques secondes
            # là où le provider raisonne en minutes.
            except (RateLimitError, LLMRateLimitError) as e:
                last_error = e
                delay, must_sleep = self._absorb_rate_limit(e, rate_limit_hits)
                rate_limit_hits += 1

                if (
                    rate_limit_spent + delay > self.rate_limit_budget
                    or rate_limit_hits >= MAX_RATE_LIMIT_HITS
                ):
                    self.llm_logger.error(
                        f"❌ Budget d'attente épuisé après "
                        f"{rate_limit_spent:.0f}s de limite de débit "
                        f"({rate_limit_hits} rejets): {e}"
                    )
                    break

                rate_limit_spent += delay
                self.llm_logger.warning(
                    f"🚦 Limite de débit atteinte (rejet {rate_limit_hits}, "
                    f"{rate_limit_spent:.0f}/{self.rate_limit_budget:.0f}s de "
                    f"budget): {e}\n⏳ Attente de {delay:.1f}s "
                    f"({'directe' if must_sleep else 'via le créneau partagé'})..."
                )
                # Sans limiteur, c'est ici qu'on patiente ; avec limiteur, le
                # créneau est déjà repoussé et `acquire()` s'en charge.
                if must_sleep:
                    time.sleep(delay)
                continue

            except (APITimeoutError, LLMTimeoutError) as e:
                last_error = e
                attempt += 1
                if attempt < self.max_retries:
                    delay = self.retry_delay * (2 ** (attempt - 1))
                    self.llm_logger.warning(
                        f"⏱️ Timeout API (tentative {attempt}/{self.max_retries}): {e}\n"
                        f"⏳ Attente de {delay:.1f}s avant nouvelle tentative..."
                    )
                    time.sleep(delay)
                    continue
                else:
                    self.llm_logger.error(
                        f"❌ Timeout API après {self.max_retries} tentatives: {e}"
                    )

            except (APIError, LLMAPIError) as e:
                last_error = e
                attempt += 1
                self.llm_logger.error(f"❌ Erreur API: {e}", exc_info=e)

            except (OpenAIError, LLMClientError) as e:
                last_error = e
                attempt += 1
                self.llm_logger.error(
                    f"❌ Erreur client LLM générique: {e}", exc_info=e
                )

            except Exception as e:
                last_error = e
                attempt += 1
                self.llm_logger.exception(
                    f"❌ Erreur inattendue lors de la requête LLM: {e}"
                )

        # Si on arrive ici, tous les retries ont échoué
        self.llm_logger.error(f"❌ Échec définitif après {self.max_retries} tentatives")
        raise (
            last_error
            if last_error
            else Exception("Échec de la requête LLM sans exception spécifique")
        )

    def _await_slot(self) -> None:
        """Attend le créneau de débit, s'il y a un limiteur.

        Appelé à chaque tentative et non une seule fois par requête : un retry
        après 429 doit reprendre un créneau, sinon le limiteur laisserait
        passer la rafale qu'il existe pour éviter.
        """
        if self.rate_limiter is not None:
            self.rate_limiter.acquire()

    def _absorb_rate_limit(
        self, error: Exception, previous_hits: int
    ) -> tuple[float, bool]:
        """Enregistre un rejet de débit et rend l'attente à observer.

        Args:
            error: Erreur de limite de débit reçue.
            previous_hits: Nombre de rejets déjà encaissés pour cette requête.

        Returns:
            Le couple (attente en secondes, faut-il dormir soi-même). Avec un
            limiteur, la pénalité a déjà repoussé le créneau et `acquire()`
            attendra : dormir en plus doublerait l'attente et fausserait la
            trace, qui annonçait 1 s là où le créneau imposait 28 s.
        """
        announced = _announced_delay(error)

        if self.rate_limiter is not None:
            return self.rate_limiter.penalize(announced), False

        if announced is not None:
            return announced, True
        return min(self.retry_delay * (3**previous_hits), MAX_RATE_LIMIT_DELAY), True

    def json_query[M: ConvertibleModel[Any]](
        self,
        system_prompt: str,
        content: str,
        response_model: type[M],
        log_name: str | None = None,
        config: LLMConfig | ClientProviderProtocol | None = None,
    ) -> M:
        log_path = self._make_log_path(log_name)
        self.llm_logger.set_exchange_file(log_path)
        if isinstance(config, ClientProviderProtocol):
            client = config
            config = None
        else:
            client = self.client

        rate_limit_spent = 0.0
        rate_limit_hits = 0

        while True:
            self._await_slot()
            try:
                json, response = client.json_request(
                    system_prompt,
                    content,
                    response_model,
                    config,
                    self.llm_logger,
                    self.max_retries,
                )
            except (RateLimitError, LLMRateLimitError) as e:
                # `json_request` porte ses propres retries de schéma, mais rien
                # sur le débit : sans cette boucle, la voie Instructor perdrait
                # son chunk là où `query` tiendrait.
                delay, must_sleep = self._absorb_rate_limit(e, rate_limit_hits)
                rate_limit_hits += 1

                if (
                    rate_limit_spent + delay > self.rate_limit_budget
                    or rate_limit_hits >= MAX_RATE_LIMIT_HITS
                ):
                    self.llm_logger.error(
                        f"❌ Budget d'attente épuisé après "
                        f"{rate_limit_spent:.0f}s de limite de débit "
                        f"({rate_limit_hits} rejets): {e}"
                    )
                    raise

                rate_limit_spent += delay
                self.llm_logger.warning(
                    f"🚦 Limite de débit atteinte (rejet {rate_limit_hits}, "
                    f"{rate_limit_spent:.0f}/{self.rate_limit_budget:.0f}s de "
                    f"budget): {e}\n⏳ Attente de {delay:.1f}s "
                    f"({'directe' if must_sleep else 'via le créneau partagé'})..."
                )
                # Sans limiteur, c'est ici qu'on patiente ; avec limiteur, le
                # créneau est déjà repoussé et `acquire()` s'en charge.
                if must_sleep:
                    time.sleep(delay)
                continue

            self.usage.record(response)
            if self.rate_limiter is not None:
                self.rate_limiter.record_success()
            return json

    def _make_log_path(self, context: str | None) -> Path:
        self._exchange_counter += 1
        timestamp = datetime.datetime.now().isoformat().replace(":", "-")
        if context:
            filename = f"llm_{context}_{self._exchange_counter:04d}_{timestamp}.log"
        else:
            filename = f"llm_{self._exchange_counter:04d}_{timestamp}.log"
        return get_session_log_path(filename)
