import os
import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import Optional, Callable, Awaitable
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam


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
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
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
        user_prompt: Optional[str] = None,
    ) -> str:
        """Envoie une requête asynchrone et appelle le callback à la fin."""
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
                # max_tokens=4000,
            )
            result = resp.choices[0].message.content
            response_text = result.strip() if result is not None else "Result Empty"
        except Exception as e:
            response_text = f"[ERREUR DE REQUÊTE] {e}"

        self._append_response(log_path, response_text)

        return response_text
