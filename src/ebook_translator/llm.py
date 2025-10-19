import os
import datetime
import sys
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import Optional, Callable, Awaitable
from openai import OpenAI, OpenAIError, APITimeoutError, RateLimitError, APIError
from openai.types.chat import ChatCompletionMessageParam

from .logger import get_logger

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
        log_dir: str = "logs",
        temperature: float = 0.85,
        max_tokens: int = 1500,
    ):
        self.model_name = model_name
        self.api_key = api_key or get_api_key()
        self.client = OpenAI(api_key=self.api_key, base_url=url)
        self.temperature = temperature
        self.max_tokens = max_tokens

        # Config Jinja2
        self.env = Environment(
            loader=FileSystemLoader(prompt_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )

        # Dossier des logs
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)

    # -----------------------------------
    # 🔹 Rendu du template
    # -----------------------------------
    def render_prompt(self, template_name: str, **kwargs) -> str:
        """Rend un template Jinja2 avec les variables données."""
        template = self.env.get_template(template_name)
        return template.render(**kwargs)

    # -----------------------------------
    # 🔹 Gestion du log
    # -----------------------------------
    def _create_log(self, prompt: str, content: str) -> str:
        """Crée un log dès l’envoi et retourne le chemin du fichier."""
        timestamp = datetime.datetime.now().isoformat().replace(":", "-")
        log_path = os.path.join(self.log_dir, f"{timestamp}.txt")

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

    def _append_response(self, log_path: str, response: str):
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
    ) -> str:
        """
        Envoie une requête au LLM avec gestion d'erreurs spécifiques.

        Args:
            system_prompt: Le prompt système définissant le comportement du LLM
            content: Le contenu à traiter

        Returns:
            La réponse du LLM ou un message d'erreur entre crochets

        Note:
            Les erreurs sont loggées et un fichier de log est créé pour chaque requête.
        """
        log_path = self._create_log(system_prompt, content)

        try:
            messages: list[ChatCompletionMessageParam] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ]
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            result = resp.choices[0].message.content
            response_text = result.strip() if result is not None else "Result Empty"
            logger.info(f"Requête LLM réussie ({len(content)} chars)")

        except APITimeoutError as e:
            logger.error(f"Timeout API: {e}")
            response_text = "[ERREUR: Timeout - Le serveur n'a pas répondu à temps]"

        except RateLimitError as e:
            logger.error(f"Limite de débit atteinte: {e}")
            response_text = "[ERREUR: Rate limit - Trop de requêtes, veuillez patienter]"

        except APIError as e:
            logger.error(f"Erreur API: {e}")
            response_text = f"[ERREUR API: {e}]"

        except OpenAIError as e:
            logger.error(f"Erreur OpenAI générique: {e}")
            response_text = f"[ERREUR OPENAI: {e}]"

        except Exception as e:
            logger.exception(f"Erreur inattendue lors de la requête LLM: {e}")
            response_text = f"[ERREUR INCONNUE: {e}]"

        self._append_response(log_path, response_text)

        return response_text
