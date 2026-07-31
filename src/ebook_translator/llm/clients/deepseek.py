from enum import StrEnum
from logging import Logger
from typing import Any, Literal, Required, cast, overload, override

from pydantic import BaseModel
from typing_extensions import TypedDict

from ebook_translator.llm.clients.client import OpenAIClientBase
from ebook_translator.llm.llm_config import (
    FullKwargs,
    GenericLLMConfig,
    LLMConfig,
    LLMConfigExport,
    LLMResponse,
    ResponseFormat,
    StreamOptions,
    UserKwargs,
)


class DeepseekModels(StrEnum):
    PRO = "deepseek-v4-pro"
    FLASH = "deepseek-v4-flash"


def _set_thinking_config(
    config: FullDeepSeekKwargs | UserDeepSeekKwargs,
    thinking: bool | Literal["high", "max"],
) -> None:
    config = cast(FullDeepSeekKwargs, config)
    if isinstance(thinking, str):
        thinking_config = "enabled"
        reasoning_effort = thinking
    else:
        thinking_config = "enabled" if thinking else "disabled"
        reasoning_effort = None

    if "extra_body" in config:
        config["extra_body"].update({"thinking": {"type": thinking_config}})
    else:
        config["extra_body"] = {"thinking": {"type": thinking_config}}
    if reasoning_effort is not None:
        config["reasoning_effort"] = reasoning_effort
    else:
        config.pop("reasoning_effort", None)


class Deepseek(
    OpenAIClientBase[
        DeepseekModels,
        Literal["high", "max"],
        "UserDeepSeekKwargs",
        "FullDeepSeekKwargs",
    ]
):
    base_url = "https://api.deepseek.com"

    type LLMConfigDS = LLMConfig[UserDeepSeekKwargs, FullDeepSeekKwargs]

    Models = DeepseekModels

    def __init__(
        self,
        model_name: Models = Models.FLASH,
        thinking: bool = False,
        api_key: str | None = None,
        config: LLMConfigDS | None = None,
    ) -> None:
        _config = self.get_model_config(model_name, thinking, config)
        super().__init__(api_key, _config)

    @overload
    @classmethod
    def _resolve_config(
        cls, config: LLMConfigExport[FullDeepSeekKwargs]
    ) -> FullDeepSeekKwargs: ...

    @overload
    @classmethod
    def _resolve_config(cls, config: GenericLLMConfig) -> UserDeepSeekKwargs: ...

    @overload
    @classmethod
    def _resolve_config(cls, config: UserDeepSeekKwargs) -> UserDeepSeekKwargs: ...

    @override
    @classmethod
    def _resolve_config(cls, config: LLMConfigDS) -> LLMConfigDS:
        if isinstance(config, LLMConfigExport):
            return config.get_properties(cls)
        elif isinstance(config, GenericLLMConfig):
            new_config: UserDeepSeekKwargs = {
                "temperature": config.temperature,
                "top_p": config.top_p,
                "max_tokens": config.max_tokens,
            }
            if config.use_thinking is not None:
                if config.use_thinking == "low":
                    thinking = "high"
                else:
                    thinking = config.use_thinking
                _set_thinking_config(new_config, thinking)
            return new_config

        return config

    @override
    @classmethod
    def get_model_preset_config(
        cls,
        model_strength: Literal["low", "high", "max"] = "high",
        thinking: bool | Literal["low", "high", "max"] = False,
        config: LLMConfigDS | None = None,
    ) -> LLMConfigExport[FullDeepSeekKwargs]:
        model_name = (
            Deepseek.Models.PRO if model_strength == "max" else Deepseek.Models.FLASH
        )
        if thinking == "low":
            thinking = "high"

        return cls.get_model_config(model_name, thinking, config)

    @override
    @classmethod
    def get_model_config(
        cls,
        model_name: Models = Models.FLASH,
        thinking: bool | Literal["high", "max"] = False,
        config: LLMConfigDS | None = None,
    ) -> LLMConfigExport[FullDeepSeekKwargs]:

        merged_config: FullDeepSeekKwargs = {
            "model": model_name.value,
        }

        _set_thinking_config(merged_config, thinking)

        if config is not None:
            config = cls._resolve_config(config)

            for k, v in config.items():
                merged_config[k] = v

        return LLMConfigExport(merged_config, cls)

    @override
    def json_request[M: BaseModel](
        self,
        system_prompt: str,
        user_instruction: str,
        response_model: type[M],
        config: LLMConfigDS | None = None,
        logger: Logger | None = None,
        max_retries: int = 1,
    ) -> tuple[M, LLMResponse]:
        config = self._resolve_config(config) if config is not None else {}
        _set_thinking_config(
            config, False
        )  # DeepSeek ne gère pas le thinking mode avec les Tools, donc on le désactive systématiquement pour les requêtes JSON
        return super().json_request(
            system_prompt, user_instruction, response_model, config, logger, max_retries
        )


class UserDeepSeekKwargs(UserKwargs, total=False):
    # ---- Échantillonnage ----
    # Ignorés silencieusement en mode thinking
    temperature: float | None  # défaut 1.0, plage [0, 2]
    top_p: float | None  # défaut 1.0, plage (0, 1]
    frequency_penalty: float | None  # plage [-2, 2]
    presence_penalty: float | None  # plage [-2, 2]

    # ---- Limites ----
    max_tokens: int | None
    # max_completion_tokens: alias OpenAI accepté par DeepSeek
    max_completion_tokens: int | None
    stop: str | list[str] | None  # max 16 séquences

    # ---- Streaming ----
    stream: bool | None
    stream_options: StreamOptions | None

    # ---- Logprobs ----
    # ⚠️ Erreur 400 sur deepseek-reasoner / mode thinking
    logprobs: bool | None
    top_logprobs: int | None  # plage [0, 20]

    # ---- Tools ----
    # tools: Iterable[Tool]
    # tool_choice: ToolChoice
    # parallel_tool_calls : accepté par compat, non garanti

    # ---- Format de sortie ----
    response_format: ResponseFormat
    extra_body: dict[str, Any]

    # ---- Identification ----
    user: str


class FullDeepSeekKwargs(UserDeepSeekKwargs, FullKwargs, total=False, extra_items=Any):
    # ---- Requis ----
    model: Required[
        (
            Literal[
                "deepseek-v4-flash",
                "deepseek-v4-pro",
                # alias legacy (route vers V4 jusqu'au 2026-07-24)
                "deepseek-chat",
                "deepseek-reasoner",
                # FIM beta
                "deepseek-coder",
            ]
            | str
        )  # tolérer les modèles à venir
    ]
    # messages: Required[Iterable[ChatCompletionMessageParam]]
    # ---- Reasoning (DeepSeek V4) ----
    # low/medium → mappés sur high ; xhigh → max
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max"] | None
    # ---- Spécifiques DeepSeek (passés via extra_body) ----

    # Active/désactive le thinking mode pour les modèles V4


class ThinkingConfig(TypedDict):
    type: Literal["enabled", "disabled"]
