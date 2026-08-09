"""Provider Mistral, bâti sur le package officiel `mistralai`.

Contrairement aux providers compatibles OpenAI, celui-ci n'utilise pas `instructor` :
la bibliothèque résout encore la classe cliente via `from mistralai import Mistral`,
chemin supprimé par `mistralai` 2.0 au profit de `mistralai.client`. La sortie
structurée passe donc par `chat.complete` alimenté par
`response_format_from_pydantic_model`, avec une boucle de correction maison
équivalente au `max_retries` d'instructor.
"""

import hashlib
from collections.abc import Mapping
from enum import StrEnum
from logging import Logger
from typing import Any, ClassVar, Literal, Never, Required, cast, overload, override

import httpx
from mistralai.client import Mistral as MistralSDK
from mistralai.client.errors import MistralError
from mistralai.client.models import ChatCompletionResponse
from mistralai.extra import response_format_from_pydantic_model
from pydantic import BaseModel, ValidationError

from ebook_translator.llm.clients.base import LLMClientBase
from ebook_translator.llm.errors import (
    LLMAPIError,
    LLMRateLimitError,
    LLMTimeoutError,
    retry_after_seconds,
)
from ebook_translator.llm.llm_config import (
    FullKwargs,
    GenericLLMConfig,
    LLMConfig,
    LLMConfigExport,
    LLMResponse,
    ResponseFormat,
    UserKwargs,
)


class MistralModels(StrEnum):
    """Alias « latest » des modèles de chat Mistral utilisés par le pipeline."""

    SMALL = "mistral-small-latest"
    MEDIUM = "mistral-medium-latest"
    LARGE = "mistral-large-latest"


def _cache_key_for(messages: list[Mapping[str, Any]]) -> str:
    """Dérive une clé de cache stable du préfixe partagé d'une conversation.

    Le prompt caching Mistral facture les tokens réutilisés à 10 % du prix d'entrée,
    mais il faut lui fournir une `prompt_cache_key` : elle n'est pas déduite du
    contenu. Le pipeline rejoue le même prompt système sur des centaines de chunks,
    donc son empreinte fait une clé naturelle — identique d'un chunk à l'autre,
    distincte d'une phase à l'autre.

    Args:
        messages: Messages de la requête, dans l'ordre d'envoi.

    Returns:
        Une clé déterministe dérivée des messages `system`.
    """
    prefix = "\n".join(
        str(m.get("content", "")) for m in messages if m.get("role") == "system"
    )
    digest = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
    return f"ebt-{digest[:24]}"


def _translate_error(error: Exception) -> Exception:
    """Traduit une erreur du SDK Mistral vers la taxonomie de `llm/errors.py`.

    Args:
        error: Exception levée par `mistralai` ou par `httpx`.

    Returns:
        L'équivalent normalisé, ou `error` inchangée si aucune correspondance.
    """
    if isinstance(error, MistralError):
        if error.status_code == 429:
            # `MistralError.headers` porte le `Retry-After` du provider : sans
            # lui, le backoff repartirait sur un délai deviné, très en deçà
            # d'une fenêtre exprimée par minute.
            return LLMRateLimitError(str(error), retry_after_seconds(error.headers))
        if error.status_code in (408, 504):
            return LLMTimeoutError(str(error))
        return LLMAPIError(str(error))
    if isinstance(error, httpx.TimeoutException):
        return LLMTimeoutError(str(error))
    if isinstance(error, httpx.HTTPError):
        return LLMAPIError(str(error))
    return error


class Mistral(
    LLMClientBase[
        MistralModels,
        Never,
        "UserMistralKwargs",
        "FullMistralKwargs",
        ChatCompletionResponse,
    ]
):
    """Client Mistral pour le pipeline de traduction.

    Example:
        >>> from ebook_translator.llm.clients.mistral import Mistral, MistralModels
        >>> client = Mistral(MistralModels.LARGE, config={"temperature": 0.3})

    Note:
        Mistral Large 3 n'expose pas de mode raisonnement : le paramètre `thinking`
        (imposé par `ClientProviderProtocol`) est accepté puis ignoré. Pour forcer
        un mode de prompt particulier, passer `prompt_mode` dans la configuration.
    """

    type LLMConfigMistral = LLMConfig[UserMistralKwargs, FullMistralKwargs]

    Models = MistralModels

    _api_key_env: ClassVar[str | None] = "MISTRAL_API_KEY"

    mistral: MistralSDK

    def __init__(
        self,
        model_name: Models = Models.LARGE,
        thinking: bool = False,
        api_key: str | None = None,
        config: LLMConfigMistral | None = None,
    ) -> None:
        """Construit le client sans ouvrir de connexion.

        Args:
            model_name: Modèle visé. `LARGE` par défaut.
            thinking: Ignoré — conservé pour l'homogénéité entre providers.
            api_key: Clé explicite. Sinon `MISTRAL_API_KEY`, puis `API_KEY`.
            config: Configuration initiale fusionnée avec celle du modèle.
        """
        _config = self.get_model_config(model_name, thinking, config)
        super().__init__(api_key, _config)

    # ------------------------------------------------------------------
    # Branchement du SDK
    # ------------------------------------------------------------------

    @override
    def _build_sdk_client(self, api_key: str) -> None:
        self.mistral = MistralSDK(api_key=api_key)

    @override
    def _finalize_params(self, params: FullMistralKwargs) -> FullMistralKwargs:
        """Renseigne `prompt_cache_key` si l'appelant ne l'a pas fixée."""
        if not params.get("prompt_cache_key"):
            messages = cast(list[Mapping[str, Any]], params.get("messages", []))
            params["prompt_cache_key"] = _cache_key_for(messages)
        return params

    @override
    def _send(self, params: FullMistralKwargs) -> ChatCompletionResponse:
        try:
            return self.mistral.chat.complete(**cast(dict[str, Any], params))
        except Exception as e:
            raise _translate_error(e) from e

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @overload
    @classmethod
    def _resolve_config(
        cls, config: LLMConfigExport[FullMistralKwargs]
    ) -> FullMistralKwargs: ...

    @overload
    @classmethod
    def _resolve_config(cls, config: GenericLLMConfig) -> UserMistralKwargs: ...

    @overload
    @classmethod
    def _resolve_config(cls, config: UserMistralKwargs) -> UserMistralKwargs: ...

    @override
    @classmethod
    def _resolve_config(cls, config: LLMConfigMistral) -> LLMConfigMistral:
        if isinstance(config, LLMConfigExport):
            return config.get_properties(cls)
        elif isinstance(config, GenericLLMConfig):
            # `use_thinking` est délibérément écarté : aucun modèle de
            # `MistralModels` n'expose de mode raisonnement.
            new_config: UserMistralKwargs = {
                "temperature": config.temperature,
                "top_p": config.top_p,
                "max_tokens": config.max_tokens,
            }
            return new_config

        return config

    @override
    @classmethod
    def get_model_preset_config(
        cls,
        model_strength: Literal["low", "high", "max"] = "high",
        thinking: bool | Literal["low", "high", "max"] = False,
        config: LLMConfigMistral | None = None,
    ) -> LLMConfigExport[FullMistralKwargs]:
        model_name = {
            "low": MistralModels.SMALL,
            "high": MistralModels.MEDIUM,
            "max": MistralModels.LARGE,
        }[model_strength]

        return cls.get_model_config(model_name, False, config)

    @override
    @classmethod
    def get_model_config(
        cls,
        model_name: Models = Models.LARGE,
        thinking: bool | Never = False,
        config: LLMConfigMistral | None = None,
    ) -> LLMConfigExport[FullMistralKwargs]:
        merged_config: FullMistralKwargs = {
            "model": model_name.value,
        }

        if config is not None:
            config = cls._resolve_config(config)

            for k, v in config.items():
                merged_config[k] = v

        return LLMConfigExport(merged_config, cls)

    # ------------------------------------------------------------------
    # Sortie structurée
    # ------------------------------------------------------------------

    @override
    def json_request[M: BaseModel](
        self,
        system_prompt: str,
        user_instruction: str,
        response_model: type[M],
        config: LLMConfigMistral | None = None,
        logger: Logger | None = None,
        max_retries: int = 1,
    ) -> tuple[M, LLMResponse]:
        """Obtient une réponse structurée validée par `response_model`.

        Reproduit le `max_retries` d'instructor : en cas d'échec de validation, le
        JSON fautif et le détail de l'erreur sont réinjectés dans la conversation
        pour que le modèle se corrige lui-même.

        Args:
            system_prompt: Prompt système.
            user_instruction: Contenu utilisateur.
            response_model: Schéma Pydantic attendu.
            config: Configuration ponctuelle.
            logger: Journal d'échange.
            max_retries: Nombre total de tentatives de validation.

        Returns:
            Le modèle validé et la réponse normalisée de la tentative retenue.

        Raises:
            ValidationError: Si la validation échoue encore après `max_retries`.
            LLMClientError: Erreur réseau ou API, déjà normalisée.
        """
        merged_config = self._prepare_params(config)
        merged_config["response_format"] = cast(
            ResponseFormat, response_format_from_pydantic_model(response_model)
        )

        messages: list[Mapping[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_instruction},
        ]

        last_error: ValidationError | None = None

        for attempt in range(max(1, max_retries)):
            merged_config["messages"] = messages
            merged_config = self._finalize_params(merged_config)

            if logger:
                self.write_header(
                    logger=logger,
                    context=None,
                    parameters=merged_config,
                )
                self.write_prompt(logger=logger, parameters=merged_config)

            response = self._send(merged_config)
            parsed_response = self.parse(response)
            if logger:
                self.write_response(logger=logger, response=parsed_response)

            content = parsed_response.content or ""
            try:
                return response_model.model_validate_json(content), parsed_response
            except ValidationError as e:
                last_error = e
                if logger:
                    logger.error(
                        f"Validation de {response_model.__name__} échouée "
                        f"(tentative {attempt + 1}/{max_retries}): {e}",
                        exc_info=e,
                    )
                messages = [
                    *messages,
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            f"Validation Error found:\n{e}\n"
                            "Recall the schema correctly, fix the errors and "
                            "answer with the corrected JSON only."
                        ),
                    },
                ]

        assert last_error is not None
        raise last_error

    # ------------------------------------------------------------------
    # Normalisation de la réponse
    # ------------------------------------------------------------------

    @override
    def parse(self, response: ChatCompletionResponse) -> LLMResponse:
        choices = response.choices or []
        choice = choices[0] if choices else None
        msg = choice.message if choice else None
        usage = response.usage

        # `UsageInfo` est déclaré `extra="allow"` : `prompt_tokens_details` n'est pas
        # un champ typé du SDK mais l'API le renvoie dès que le cache est sollicité.
        cached_tokens = 0
        details = (
            (usage.model_extra or {}).get("prompt_tokens_details") if usage else None
        )
        if isinstance(details, Mapping):
            cached_tokens = int(
                cast(Mapping[str, Any], details).get("cached_tokens", 0)
            )

        return LLMResponse(
            content=_content_to_text(msg.content) if msg else None,
            reasoning=None,
            tool_calls=cast(Any, msg.tool_calls) if msg else None,
            finish_reason=(choice.finish_reason or "") if choice else "",
            prompt_tokens=(usage.prompt_tokens or 0) if usage else 0,
            completion_tokens=(usage.completion_tokens or 0) if usage else 0,
            cached_tokens=cached_tokens,
            reasoning_tokens=0,
            model=response.model,
            response_id=response.id,
        )


def _content_to_text(content: Any) -> str | None:
    """Aplatit le contenu d'un message Mistral en texte.

    `AssistantMessage.content` vaut soit une chaîne, soit une liste de blocs typés
    (texte, référence, image) — seuls les blocs textuels sont conservés.

    Args:
        content: Valeur brute de `message.content`.

    Returns:
        Le texte concaténé, ou `None` si le message n'en porte aucun.
    """
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for chunk in cast(list[Any], content):
            text = getattr(chunk, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts) if parts else None
    return None


class UserMistralKwargs(UserKwargs, total=False):
    """Paramètres que l'utilisateur final peut fournir à `chat.complete`."""

    # ---- Échantillonnage ----
    temperature: float | None  # plage [0, 1.5] recommandée par Mistral
    top_p: float | None  # défaut 1.0
    presence_penalty: float | None  # plage [-2, 2]
    frequency_penalty: float | None  # plage [-2, 2]
    random_seed: int | None

    # ---- Limites ----
    max_tokens: int | None
    stop: str | list[str] | None
    n: int | None

    # ---- Format de sortie ----
    response_format: ResponseFormat

    # ---- Spécifiques Mistral ----
    # Le caching facture les tokens réutilisés à 10 % du prix d'entrée, par blocs de
    # 64 tokens. Laissé vide, il est dérivé du prompt système (cf. `_finalize_params`).
    prompt_cache_key: str | None
    prompt_mode: Literal["reasoning"] | None
    safe_prompt: bool | None


class FullMistralKwargs(UserMistralKwargs, FullKwargs, total=False, extra_items=Any):
    """Paramètres complets envoyés à l'API, `model` compris."""

    # ---- Requis ----
    model: Required[
        (
            Literal[
                "mistral-small-latest",
                "mistral-medium-latest",
                "mistral-large-latest",
            ]
            | str  # tolérer les versions épinglées et les modèles à venir
        )
    ]


__all__ = ["FullMistralKwargs", "Mistral", "MistralModels", "UserMistralKwargs"]
