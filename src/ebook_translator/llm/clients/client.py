import datetime
import logging
import os
import pprint
import sys
from abc import ABC, abstractmethod
from enum import StrEnum
from logging import Logger
from typing import (
    Any,
    Literal,
    Protocol,
    Self,
    cast,
    overload,
    runtime_checkable,
)

import instructor
from dotenv import load_dotenv
from instructor import Mode
from instructor.core import Hooks
from openai import OpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from openai.types.chat.completion_create_params import (
    CompletionCreateParamsNonStreaming,
)
from pydantic import BaseModel

from ebook_translator.llm.llm_config import (
    FullKwargs,
    GenericLLMConfig,
    LLMConfig,
    LLMConfigExport,
    LLMResponse,
    UserKwargs,
)


def get_api_key(name: str | None = None) -> str:
    # Charger les variables d'environnement depuis .env
    load_dotenv()

    # Configuration du LLM avec validation
    api_key = None
    if name:
        api_key = os.getenv(name)
    api_key = api_key or os.getenv("API_KEY")

    if not api_key:
        from ebook_translator.logger import get_logger

        logger = get_logger(__name__)
        logger.error("\n❌ ERREUR : La clé API DeepSeek n'est pas définie.")
        logger.error("\nPour configurer :")
        logger.error("  1. Copiez .env.example en .env")
        logger.error(
            "  2. Obtenez une clé API sur https://platform.deepseek.com/api_keys"
        )
        logger.error("  3. Ajoutez votre clé dans .env : DEEPSEEK_API_KEY=sk-votre-cle")
        logger.error(
            "\nDocumentation : voir CLAUDE.md section 'Configuration des clés API'\n"
        )
        sys.exit(1)
    return api_key


@runtime_checkable
class ClientProviderProtocol[U: UserKwargs = UserKwargs, D: FullKwargs = FullKwargs](
    Protocol
):
    @property
    def parameters(self) -> FullKwargs: ...

    def set_preset_config(
        self,
        model_strength: Literal["low", "high", "max"],
        thinking: bool | Literal["low", "high", "max"],
        config: GenericLLMConfig | None = None,
    ) -> Self: ...

    @classmethod
    def get_model_preset_config(
        cls,
        model_strength: Literal["low", "high", "max"],
        thinking: bool | Literal["low", "high", "max"],
        config: GenericLLMConfig | None = None,
    ) -> LLMConfigExport[D]: ...

    def request(
        self,
        system_prompt: str,
        user_instruction: str,
        config: LLMConfig[U, D] | None,
        logger: Logger | None,
    ) -> LLMResponse: ...

    def json_request[M: BaseModel](
        self,
        system_prompt: str,
        user_instruction: str,
        response_model: type[M],
        config: LLMConfig[U, D] | None,
        logger: Logger | None,
    ) -> tuple[M, LLMResponse]: ...


class OpenAIClientBase[
    ModelsEnum: StrEnum,
    ThinkingEnum: str,
    UserData: UserKwargs,
    Data: FullKwargs,
](ClientProviderProtocol[UserData, Data], ABC):
    """OpenAI API wrapper"""

    base_url: str

    Models: type[ModelsEnum]

    # Data = CompletionCreateParamsNonStreaming

    _parameters: Data

    @property
    def parameters(self) -> Data:
        return self._parameters

    @parameters.setter
    def parameters(self, config: Data | LLMConfigExport[Data]) -> None:
        if isinstance(config, LLMConfigExport):
            config = config.get_properties(self)
        self._parameters = config

    def __init__(
        self,
        api_key: str | None = None,
        config: LLMConfig[UserData, Data] | None = None,
    ) -> None:
        if not api_key:
            api_key = get_api_key(api_key)
        self.openai = OpenAI(api_key=api_key, base_url=self.base_url)
        self.instructor = None
        self._parameters = cast(Data, {})  # Initialisation temporaire

        if config is None:
            self.set_default_config()
        elif isinstance(config, LLMConfigExport):
            self.applied_config(config)
        else:
            self.applied_config(self.get_default_config(config))

    @overload
    @classmethod
    def _resolve_config(cls, config: LLMConfigExport[Data]) -> Data: ...

    @overload
    @classmethod
    def _resolve_config(cls, config: GenericLLMConfig) -> UserData: ...

    @overload
    @classmethod
    def _resolve_config(cls, config: UserData) -> UserData: ...

    @classmethod
    @abstractmethod
    def _resolve_config(cls, config: LLMConfig[UserData, Data]) -> UserData | Data: ...

    @classmethod
    @abstractmethod
    def get_model_preset_config(
        cls,
        model_strength: Literal["low", "high", "max"],
        thinking: bool | Literal["low", "high", "max"],
        config: LLMConfig[UserData, Data] | None = None,
    ) -> LLMConfigExport[Data]: ...

    def set_preset_config(
        self,
        model_strength: Literal["low", "high", "max"],
        thinking: bool | Literal["low", "high", "max"],
        config: LLMConfig[UserData, Data] | None = None,
    ) -> Self:
        preset_config = self.get_model_preset_config(model_strength, thinking, config)
        self.applied_config(preset_config)
        return self

    @classmethod
    @abstractmethod
    def get_model_config(
        cls,
        model_name: ModelsEnum,
        thinking: bool | ThinkingEnum,
        config: LLMConfig[UserData, Data] | None = None,
    ) -> LLMConfigExport[Data]: ...

    def set_config(
        self,
        model_name: ModelsEnum,
        thinking: bool | ThinkingEnum,
        config: LLMConfig[UserData, Data] | None = None,
    ) -> Self:
        _config = self.get_model_config(model_name, thinking, config)
        self.applied_config(_config)
        return self

    @classmethod
    def get_default_config(
        cls, config: LLMConfig[UserData, Data] | None = None
    ) -> LLMConfigExport[Data]:
        return cls.get_model_preset_config(
            model_strength="high", thinking=False, config=config
        )

    def set_default_config(
        self, config: LLMConfig[UserData, Data] | None = None
    ) -> Self:
        default_config = self.get_default_config(config)
        self.applied_config(default_config)
        return self

    def merged_config(self, config: LLMConfig[UserData, Data]) -> LLMConfigExport[Data]:
        _config = self._resolve_config(config)

        merged = self.parameters.copy()
        for k, v in _config.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        return LLMConfigExport[Data](merged, type(self))

    def applied_config(self, config: LLMConfig[UserData, Data]) -> None:
        self.parameters = self.merged_config(config)

    def request(
        self,
        system_prompt: str,
        user_instruction: str,
        config: LLMConfig[UserData, Data] | None = None,
        logger: Logger | None = None,
    ) -> LLMResponse:
        try:
            merged_config = (
                self.merged_config(config) if config else self.parameters.copy()
            )

            if isinstance(merged_config, LLMConfigExport):
                merged_config = merged_config.get_properties(self)

            merged_config["messages"] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_instruction},
            ]

            if logger:
                self.write_header(
                    logger=logger,
                    context=None,
                    parameters=merged_config,
                )
                self.write_prompt(logger=logger, parameters=merged_config)

            response = self.openai.chat.completions.create(
                **cast(CompletionCreateParamsNonStreaming, merged_config),
            )
            parsed_response = self.parse(response)
            if logger:
                self.write_response(logger=logger, response=parsed_response)
            return parsed_response

        except Exception as e:
            if logger:
                logger.error(f"Error during OpenAI API request: {e}")
            raise e

    def json_request[M: BaseModel](
        self,
        system_prompt: str,
        user_instruction: str,
        response_model: type[M],
        config: LLMConfig[UserData, Data] | None = None,
        logger: Logger | None = None,
    ) -> tuple[M, LLMResponse]:
        if self.instructor is None:
            self.instructor = instructor.from_openai(
                self.openai, mode=Mode.TOOLS_STRICT
            )

        merged_config = self.merged_config(config) if config else self.parameters.copy()

        if isinstance(merged_config, LLMConfigExport):
            merged_config = merged_config.get_properties(self)

        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_instruction},
        ]

        if logger:
            self.write_header(
                logger=logger,
                context=None,
                parameters=merged_config,
            )

            def log_request(*args: Any, **kwargs: Any):
                # kwargs contient messages, model, response_format, tools...
                logger.info("Appel LLM par instructor avec les paramètres suivants :")

                for k, v in kwargs.items():
                    if k == "messages":
                        continue
                    if k == "tools":
                        logger.info(
                            k
                            + " = "
                            + pprint.pformat(v, indent=4, width=80, compact=False)
                        )
                        continue
                    logger.info(str(k) + " = " + str(v))
                self.write_prompt(
                    logger=logger, parameters=kwargs
                )  # pyright: ignore[reportArgumentType]

            def log_response(response: ChatCompletion):
                # response = ChatCompletion brut, avant parsing pydantic
                parsed = self.parse(response)
                self.write_response(logger=logger, response=parsed)

            def log_error(error: Any):
                # ValidationError pydantic — utile pour distinguer
                # erreur structurelle vs erreur API
                logger.error(f"Error during OpenAI API request: {error}")

            hooks = Hooks()

            hooks.on("completion:kwargs", log_request)
            hooks.on("completion:response", log_response)
            hooks.on("parse:error", log_error)
            hooks.on("completion:error", log_error)
        else:
            hooks = None

        data, response = self.instructor.create_with_completion(
            response_model=response_model,
            messages=messages,
            hooks=hooks,
            **cast(dict[str, Any], merged_config),
        )
        return data, self.parse(response)

    @staticmethod
    def write_header(
        logger: logging.Logger,
        context: str | None,
        parameters: Data,
    ) -> None:
        """Write the request header to a new exchange log file.

        Args:
            path: Target file path (created or overwritten).
            system_prompt: System prompt sent to the LLM.
            user_prompt: User content sent to the LLM.
            model: LLM model name.
            context: Optional label (e.g. "chunk_042").
        """
        timestamp = datetime.datetime.now().isoformat().replace(":", "-")
        clear_data = {k: v for k, v in parameters.items() if k != "messages"}
        header = (
            f"=== LLM REQUEST LOG ===\n"
            f"Timestamp : {timestamp}\n"
            f"Model     : {parameters.get('model', 'unknown')}\n"
            f"Context   : {context or 'N/A'}\n"
            f"parameters: {clear_data}\n"
        )
        logger.info(header.strip() + "\n")

    @staticmethod
    def write_prompt(logger: logging.Logger, parameters: Data) -> None:
        messages: list[ChatCompletionMessageParam] = parameters.get("messages", [])
        logger.info("\n=== MESSAGES ===")
        for msg in messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "NO CONTENT")
            logger.info(f"\n--- {role} ---\n{content}")

    def write_response(
        self,
        logger: logging.Logger,
        response: LLMResponse,
    ) -> None:
        """Append the LLM response (and optional reasoning) to an exchange log file.

        Args:
            path: Path written by write_exchange_header.
            response: LLM response text.
            reasoning: Optional reasoning content (deepseek-reasoner).
        """
        logger.info("\n=== RESPONSE ===\n")
        if response.reasoning:
            logger.info(f"--- 🧠 REASONING ---\n{response.reasoning}")
        if response.content:
            logger.info(f"--- 📝 CONTENT ---\n{response.content}")

        if response.tool_calls:
            logger.info("--- 🔧 TOOL CALLS ---")
            for idx, tool_call in enumerate(response.tool_calls):
                if tool_call.type == "function":
                    logger.info(f"Tool call {idx + 1}: {tool_call.function.name}")
                    logger.info(f"Arguments: {tool_call.function.arguments}")

    @staticmethod
    def parse(response: ChatCompletion) -> LLMResponse:
        choice = response.choices[0]
        msg = choice.message
        usage = response.usage
        prompt_details = usage.prompt_tokens_details if usage else None
        completion_details = usage.completion_tokens_details if usage else None
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        cached_tokens = 0
        if usage:
            cached_tokens = getattr(usage, "prompt_cache_hit_tokens", 0)

        if prompt_details:
            cached_tokens = getattr(prompt_details, "cached_tokens", cached_tokens)

        return LLMResponse(
            content=msg.content,
            reasoning=getattr(msg, "reasoning_content", None),
            tool_calls=msg.tool_calls,
            finish_reason=choice.finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            reasoning_tokens=(
                getattr(completion_details, "reasoning_tokens", 0)
                if completion_details
                else 0
            ),
            model=response.model,
            response_id=response.id,
        )
