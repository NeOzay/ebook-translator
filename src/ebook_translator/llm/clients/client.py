"""Socle des providers exposant une API compatible OpenAI.

`get_api_key` et `ClientProviderProtocol` sont réexportés ici : ils vivent
désormais dans `base.py` et `protocol.py`, mais de nombreux modules les importent
depuis ce chemin historique.
"""

import pprint
from enum import StrEnum
from logging import Logger
from typing import Any, cast, override

import instructor
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
    LLMConfig,
    LLMResponse,
    UserKwargs,
)

from .base import LLMClientBase, get_api_key
from .protocol import ClientProviderProtocol

__all__ = ["ClientProviderProtocol", "OpenAIClientBase", "get_api_key"]


class OpenAIClientBase[
    ModelsEnum: StrEnum,
    ThinkingEnum: str,
    UserData: UserKwargs,
    Data: FullKwargs,
](LLMClientBase[ModelsEnum, ThinkingEnum, UserData, Data, ChatCompletion]):
    """OpenAI API wrapper"""

    base_url: str

    openai: OpenAI

    @override
    def _build_sdk_client(self, api_key: str) -> None:
        self.openai = OpenAI(api_key=api_key, base_url=self.base_url)
        self.instructor = None

    @override
    def _send(self, params: Data) -> ChatCompletion:
        return self.openai.chat.completions.create(
            **cast(CompletionCreateParamsNonStreaming, params),
        )

    @override
    def json_request[M: BaseModel](
        self,
        system_prompt: str,
        user_instruction: str,
        response_model: type[M],
        config: LLMConfig[UserData, Data] | None = None,
        logger: Logger | None = None,
        max_retries: int = 1,
    ) -> tuple[M, LLMResponse]:
        if self.instructor is None:
            self.instructor = instructor.from_openai(self.openai, mode=Mode.JSON)

        merged_config = self._prepare_params(config)

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
                self.write_prompt(logger=logger, parameters=kwargs)

            def log_response(response: ChatCompletion):
                # response = ChatCompletion brut, avant parsing pydantic
                parsed = self.parse(response)
                self.write_response(logger=logger, response=parsed)

            def log_error(error: Any):
                # ValidationError pydantic — utile pour distinguer
                # erreur structurelle vs erreur API. `exc_info` fournit la
                # traceback : sans elle, le log ne pointe que sur ce hook et
                # non sur le site réel de l'erreur.
                logger.error(
                    f"Error during OpenAI API request: {error}",
                    exc_info=error if isinstance(error, BaseException) else None,
                )

            hooks = Hooks()

            hooks.on("completion:kwargs", log_request)
            hooks.on("completion:response", log_response)
            hooks.on("parse:error", log_error)
            hooks.on("completion:error", log_error)
        else:
            hooks = None

        # `max_retries` d'instructor : l'erreur de validation Pydantic est
        # réinjectée dans la conversation pour que le modèle corrige lui-même
        # (JSON tronqué, contrainte de longueur dépassée, champ manquant).
        data, response = self.instructor.create_with_completion(
            response_model=response_model,
            messages=messages,
            hooks=hooks,
            max_retries=max_retries,
            **cast(dict[str, Any], merged_config),
        )
        return data, self.parse(response)

    @override
    def parse(self, response: ChatCompletion) -> LLMResponse:
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
