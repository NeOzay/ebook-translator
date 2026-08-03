"""Contrat structurel que doit remplir tout provider LLM.

Isolé dans son propre module pour que le socle (`base.py`) et les implémentations
concrètes puissent l'importer sans cycle.
"""

from logging import Logger
from typing import Literal, Protocol, Self, runtime_checkable

from pydantic import BaseModel

from ebook_translator.llm.llm_config import (
    FullKwargs,
    GenericLLMConfig,
    LLMConfig,
    LLMConfigExport,
    LLMResponse,
    UserKwargs,
)


@runtime_checkable
class ClientProviderProtocol[U: UserKwargs = UserKwargs, D: FullKwargs = FullKwargs](
    Protocol
):
    """Interface minimale d'un client LLM.

    `@runtime_checkable` est structurant : `LLM.query` / `LLM.json_query` font un
    `isinstance` sur ce protocole pour distinguer une configuration d'un client de
    substitution passé à la place.
    """

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
        max_retries: int = 1,
    ) -> tuple[M, LLMResponse]: ...
