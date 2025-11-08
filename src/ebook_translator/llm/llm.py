import os
import datetime
from pathlib import Path
import sys
import time
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import Optional, Callable, Awaitable
from openai import OpenAI, OpenAIError, APITimeoutError, RateLimitError, APIError
from openai.types.chat import ChatCompletionMessageParam

from ..logger import get_logger, get_session_log_path
from .template_renderers import TemplateRenderer

logger = get_logger(__name__)


def get_api_key() -> str:
    # Charger les variables d'environnement depuis .env
    load_dotenv()

    # Configuration du LLM avec validation
    api_key = os.getenv("API_KEY")
    if not api_key:
        print("\n❌ ERREUR : La clé API DeepSeek n'est pas définie.", file=sys.stderr)
        print("\nPour configurer :", file=sys.stderr)
        print("  1. Copiez .env.example en .env", file=sys.stderr)
        print(
            "  2. Obtenez une clé API sur https://platform.deepseek.com/api_keys",
            file=sys.stderr,
        )
        print(
            "  3. Ajoutez votre clé dans .env : DEEPSEEK_API_KEY=sk-votre-cle",
            file=sys.stderr,
        )
        print(
            "\nDocumentation : voir CLAUDE.md section 'Configuration des clés API'\n",
            file=sys.stderr,
        )
        sys.exit(1)
    return api_key


class LLM:
    """
    Classe asynchrone pour gérer un LLM (DeepSeek, GPT, etc.)
    avec :
      - rendu de templates Jinja2,
      - logs créés à l’envoi,
      - callback exécuté à la réception,
      - exécution parallèle avec limite de simultanéité.
    """

    def __init__(
        self,
        model_name: str,
        url: str,
        api_key: Optional[str] = None,
        prompt_dir: str = "template",
        temperature: float = 0.5,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        self.model_name = model_name
        self.api_key = api_key or get_api_key()
        self.client = OpenAI(api_key=self.api_key, base_url=url)
        self.temperature = temperature
        self.max_tokens = 4000
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Compteur pour nommage unique des logs
        self._log_counter = 0

        # Renderer encapsulé pour templates typés (API recommandée)
        self.renderer = TemplateRenderer(prompt_dir)

    # -----------------------------------
    # 🔹 Rendu du template
    # -----------------------------------
    def render_prompt(self, template_name: str, **kwargs) -> str:
        """
        Rend un template Jinja2 avec les variables données.

        Note:
            Cette méthode est conservée pour rétrocompatibilité.
            Pour une API typée et simplifiée, utilisez `self.renderer.render_XXX()`.

        Example:
            >>> # API recommandée (typée)
            >>> prompt = llm.renderer.render_translate(target_language="fr")
            >>>
            >>> # API legacy (non typée, conservée pour compatibilité)
            >>> prompt = llm.render_prompt("translate_base.jinja", target_language="fr")

        Args:
            template_name: Nom du fichier template (ex: "translate_base.jinja")
            **kwargs: Variables à passer au template

        Returns:
            Prompt rendu
        """
        return self.renderer.render_prompt(template_name, **kwargs)

    # -----------------------------------
    # 🔹 Gestion du log
    # -----------------------------------
    def _create_log(
        self, prompt: str, content: str, context: Optional[str] = None
    ) -> Path:
        """
        Prépare les données du log et retourne le chemin du fichier.

        Le fichier ne sera créé qu'au moment de l'ajout de la réponse (lazy).

        Args:
            prompt: Le prompt système envoyé au LLM
            content: Le contenu à traiter
            context: Contexte optionnel pour nommer le fichier (ex: "chunk_042", "retry_phase1")

        Returns:
            Chemin du fichier de log (non encore créé)
        """

        timestamp = datetime.datetime.now().isoformat().replace(":", "-")

        # Générer un nom de fichier contextuel
        self._log_counter += 1
        if context:
            # Format : llm_<context>_<counter>.log
            filename = f"llm_{context}_{self._log_counter:04d}_{timestamp}.log"
        else:
            # Format par défaut : llm_<counter>.log
            filename = f"llm_{self._log_counter:04d}_{timestamp}.log"

        log_path = get_session_log_path(filename)

        header = (
            f"=== LLM REQUEST LOG ===\n"
            f"Timestamp : {timestamp}\n"
            f"Model     : {self.model_name}\n"
            f"Prompt len: {len(prompt)} chars\n"
            f"{'-'*40}\n\n"
            f"--- PROMPT ---\n{prompt}\n\n"
            f"--- CONTENT ---\n{content}\n\n"
            f"--- RESPONSE ---\n"
        )
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(header)
        return log_path

    def _append_response(self, log_path: Path, response: str):
        """Ajoute la réponse à la fin du log existant."""
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(response.strip() + "\n")

    # -----------------------------------
    # 🔹 Requête asynchrone simple
    # -----------------------------------
    def query(
        self,
        system_prompt: str,
        content: str,
        context: Optional[str] = None,
        use_reasoning_mode: bool = False,
        use_json_mode: bool = False,
    ) -> str:
        """
        Envoie une requête au LLM avec gestion d'erreurs spécifiques et retry automatique.

        Args:
            system_prompt: Le prompt système définissant le comportement du LLM
            content: Le contenu à traiter
            context: Contexte optionnel pour nommer le fichier de log
                    (ex: "chunk_042", "retry_phase1", "validation")
            use_reasoning_mode: Si True, utilise deepseek-reasoner au lieu de deepseek-chat.
                               Le modèle génère alors un reasoning_content explicite.
            use_json_mode: Si True, force le LLM à retourner du JSON valide.
                          Utilise response_format={'type': 'json_object'} de l'API DeepSeek.

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
        log_path = self._create_log(system_prompt, content, context)
        last_error: Optional[Exception] = None

        # Choisir le modèle selon le mode
        model_name = "deepseek-reasoner" if use_reasoning_mode else self.model_name

        # Log du mode utilisé
        if use_reasoning_mode:
            logger.info(f"🧠 Mode raisonnement activé pour : {context}")

        for attempt in range(self.max_retries):
            try:
                messages: list[ChatCompletionMessageParam] = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ]

                # Préparer response_format si JSON mode activé
                response_format = None
                if use_json_mode:
                    response_format = {'type': 'json_object'}

                resp = self.client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    response_format=response_format,  # type: ignore
                )
                result = resp.choices[0].message.content
                response_text = result.strip() if result is not None else "Result Empty"

                # Extraire le raisonnement si présent (deepseek-reasoner)
                reasoning_text = ""
                if hasattr(resp.choices[0].message, "reasoning_content"):
                    reasoning_content = resp.choices[0].message.reasoning_content  # type: ignore
                    reasoning_text = (
                        reasoning_content if reasoning_content is not None else ""
                    )

                if attempt > 0:
                    logger.info(
                        f"✅ Requête LLM réussie après {attempt + 1} tentative(s) "
                        f"({len(content)} chars)"
                    )
                else:
                    logger.info(f"✅ Requête LLM réussie ({len(content)} chars)")

                # Logger avec raisonnement séparé si présent
                if reasoning_text:
                    log_content = f"""
{'=' * 80}
🧠 REASONING (deepseek-reasoner):
{'=' * 80}
{reasoning_text}

{'=' * 80}
📝 RESPONSE:
{'=' * 80}
{response_text}
"""
                    self._append_response(log_path, log_content)
                else:
                    self._append_response(log_path, response_text)

                return response_text

            except APITimeoutError as e:
                last_error = e
                logger.warning(
                    f"⏱️ Timeout API (tentative {attempt + 1}/{self.max_retries}): {e}"
                )
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2**attempt)
                    logger.info(
                        f"⏳ Attente de {delay:.1f}s avant nouvelle tentative..."
                    )
                    time.sleep(delay)
                    continue

            except RateLimitError as e:
                last_error = e
                logger.warning(
                    f"🚦 Limite de débit atteinte (tentative {attempt + 1}/{self.max_retries}): {e}"
                )
                if attempt < self.max_retries - 1:
                    # Pour rate limit, attendre plus longtemps
                    delay = self.retry_delay * (3**attempt)
                    logger.info(
                        f"⏳ Attente de {delay:.1f}s avant nouvelle tentative..."
                    )
                    time.sleep(delay)
                    continue

            except APIError as e:
                # Les erreurs API ne sont généralement pas récupérables par retry
                logger.error(f"❌ Erreur API: {e}")
                response_text = f"[ERREUR API: {e}]"
                self._append_response(log_path, response_text)
                return response_text

            except OpenAIError as e:
                logger.error(f"❌ Erreur OpenAI générique: {e}")
                response_text = f"[ERREUR OPENAI: {e}]"
                self._append_response(log_path, response_text)
                return response_text

            except Exception as e:
                logger.exception(f"❌ Erreur inattendue lors de la requête LLM: {e}")
                response_text = f"[ERREUR INCONNUE: {e}]"
                self._append_response(log_path, response_text)
                return response_text

        # Si on arrive ici, tous les retries ont échoué
        if isinstance(last_error, APITimeoutError):
            response_text = (
                f"[ERREUR: Timeout après {self.max_retries} tentatives - "
                f"Le serveur n'a pas répondu à temps]"
            )
        elif isinstance(last_error, RateLimitError):
            response_text = (
                f"[ERREUR: Rate limit après {self.max_retries} tentatives - "
                f"Trop de requêtes, veuillez patienter]"
            )
        else:
            response_text = f"[ERREUR: Échec après {self.max_retries} tentatives]"

        logger.error(f"❌ Échec définitif après {self.max_retries} tentatives")
        self._append_response(log_path, response_text)
        return response_text
