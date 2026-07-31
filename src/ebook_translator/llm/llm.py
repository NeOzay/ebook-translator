import datetime
import time
from pathlib import Path
from typing import Any

from openai import APIError, APITimeoutError, OpenAIError, RateLimitError

from ebook_translator.llm.clients.client import ClientProviderProtocol
from ebook_translator.llm.llm_config import (
    LLMConfig,
)
from template.types import ConvertibleModel

from ..logger import get_logger, get_session_log_path
from .logger import LLMLogger
from .template_renderers import DEFAULT_PROMPT_DIR, TemplateRenderer

logger = get_logger(__name__)


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
    ):
        self.client: ClientProviderProtocol[Any, Any] = client
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._exchange_counter = 0

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
            Les erreurs Timeout et RateLimitError déclenchent un retry automatique
            avec backoff exponentiel.
            Le fichier de log n'est créé qu'au moment où la réponse est disponible.

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

        for attempt in range(self.max_retries):
            try:
                result = client.request(
                    system_prompt=system_prompt,
                    user_instruction=content,
                    config=config,
                    logger=self.llm_logger,
                )

                response_text = result.content if result.content else "Result Empty"

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

            except APITimeoutError as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2**attempt)
                    self.llm_logger.warning(
                        f"⏱️ Timeout API (tentative {attempt + 1}/{self.max_retries}): {e}\n"
                        f"⏳ Attente de {delay:.1f}s avant nouvelle tentative..."
                    )
                    time.sleep(delay)
                    continue
                else:
                    self.llm_logger.error(
                        f"❌ Timeout API après {self.max_retries} tentatives: {e}"
                    )

            except RateLimitError as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (3**attempt)
                    self.llm_logger.warning(
                        f"🚦 Limite de débit atteinte (tentative {attempt + 1}/{self.max_retries}): {e}\n"
                        f"⏳ Attente de {delay:.1f}s avant nouvelle tentative..."
                    )
                    time.sleep(delay)
                    continue
                else:
                    self.llm_logger.error(
                        f"❌ Limite de débit après {self.max_retries} tentatives: {e}"
                    )

            except APIError as e:
                last_error = e
                self.llm_logger.error(f"❌ Erreur API: {e}", exc_info=e)

            except OpenAIError as e:
                last_error = e
                self.llm_logger.error(f"❌ Erreur OpenAI générique: {e}", exc_info=e)

            except Exception as e:
                last_error = e
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

        json, _ = client.json_request(
            system_prompt,
            content,
            response_model,
            config,
            self.llm_logger,
            self.max_retries,
        )
        return json

    def _make_log_path(self, context: str | None) -> Path:
        self._exchange_counter += 1
        timestamp = datetime.datetime.now().isoformat().replace(":", "-")
        if context:
            filename = f"llm_{context}_{self._exchange_counter:04d}_{timestamp}.log"
        else:
            filename = f"llm_{self._exchange_counter:04d}_{timestamp}.log"
        return get_session_log_path(filename)
