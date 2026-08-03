"""Socle agnostique partagé par tous les providers LLM.

`LLMClientBase` porte tout ce qui ne dépend pas d'un SDK particulier : la machinerie
de configuration (presets, fusion, export) et la journalisation des échanges. Les
providers concrets n'ont plus qu'à brancher leur SDK via quatre points d'extension —
`_build_sdk_client`, `_send`, `parse` et `json_request`.
"""

import datetime
import logging
import os
import sys
from abc import ABC, abstractmethod
from collections.abc import Mapping
from enum import StrEnum
from logging import Logger
from typing import Any, ClassVar, Literal, Self, cast, overload

from dotenv import load_dotenv
from pydantic import BaseModel

from ebook_translator.llm.llm_config import (
    FullKwargs,
    GenericLLMConfig,
    LLMConfig,
    LLMConfigExport,
    LLMResponse,
    UserKwargs,
)

from .protocol import ClientProviderProtocol


def get_api_key(name: str | None = None) -> str:
    """Résout la clé API depuis l'environnement (`.env` inclus).

    Args:
        name: Nom de la variable d'environnement propre au provider (par exemple
            `"MISTRAL_API_KEY"`). Elle est consultée en premier ; `API_KEY` sert
            de repli commun à tous les providers.

    Returns:
        La clé API trouvée.

    Note:
        En l'absence de clé, la fonction journalise la marche à suivre puis appelle
        `sys.exit(1)` — elle ne retourne pas.
    """
    load_dotenv()

    api_key = None
    if name:
        api_key = os.getenv(name)
    api_key = api_key or os.getenv("API_KEY")

    if not api_key:
        from ebook_translator.logger import get_logger

        expected = f"{name} (ou API_KEY)" if name else "API_KEY"
        logger = get_logger(__name__)
        logger.error(f"\n❌ ERREUR : la clé API n'est pas définie ({expected}).")
        logger.error("\nPour configurer :")
        logger.error("  1. Copiez .env.example en .env")
        logger.error(f"  2. Ajoutez votre clé dans .env : {name or 'API_KEY'}=...")
        logger.error(
            "\nDocumentation : voir CLAUDE.md section 'Environment Variables'\n"
        )
        sys.exit(1)
    return api_key


class LLMClientBase[
    ModelsEnum: StrEnum,
    ThinkingEnum: str,
    UserData: UserKwargs,
    Data: FullKwargs,
    RawResponse,
](ClientProviderProtocol[UserData, Data], ABC):
    """Base commune aux clients LLM, indépendante de tout SDK.

    Les paramètres de type décrivent, dans l'ordre : l'énumération des modèles du
    provider, les niveaux de « thinking » qu'il accepte, les kwargs que
    l'utilisateur final peut fournir, les kwargs complets envoyés à l'API, et le
    type de réponse brute que rend son SDK.
    """

    Models: type[ModelsEnum]

    _api_key_env: ClassVar[str | None] = None
    """Variable d'environnement propre au provider, consultée avant `API_KEY`."""

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
        """Construit le client et applique sa configuration initiale.

        Args:
            api_key: Clé API explicite. Si absente, elle est résolue depuis
                l'environnement via `_api_key_env` puis `API_KEY`.
            config: Configuration initiale. `None` applique la configuration par
                défaut du provider.
        """
        if not api_key:
            api_key = get_api_key(self._api_key_env)
        self._build_sdk_client(api_key)
        self._parameters = cast(Data, {})  # Initialisation temporaire

        if config is None:
            self.set_default_config()
        elif isinstance(config, LLMConfigExport):
            self.applied_config(config)
        else:
            self.applied_config(self.get_default_config(config))

    # ------------------------------------------------------------------
    # Points d'extension propres au SDK
    # ------------------------------------------------------------------

    @abstractmethod
    def _build_sdk_client(self, api_key: str) -> None:
        """Instancie le client du SDK et le stocke sur `self`."""

    @abstractmethod
    def _send(self, params: Data) -> RawResponse:
        """Exécute une complétion texte et rend la réponse brute du SDK."""

    @abstractmethod
    def parse(self, response: RawResponse) -> LLMResponse:
        """Normalise une réponse brute du SDK en `LLMResponse`."""

    @abstractmethod
    def json_request[M: BaseModel](
        self,
        system_prompt: str,
        user_instruction: str,
        response_model: type[M],
        config: LLMConfig[UserData, Data] | None = None,
        logger: Logger | None = None,
        max_retries: int = 1,
    ) -> tuple[M, LLMResponse]:
        """Exécute une requête à sortie structurée validée par `response_model`."""

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

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

    def _prepare_params(self, config: LLMConfig[UserData, Data] | None) -> Data:
        """Fusionne `config` avec les paramètres courants et rend un dict prêt à envoyer."""
        merged_config = self.merged_config(config) if config else self.parameters.copy()
        if isinstance(merged_config, LLMConfigExport):
            merged_config = merged_config.get_properties(self)
        return merged_config

    def _finalize_params(self, params: Data) -> Data:
        """Dernier ajustement des paramètres, messages compris, juste avant l'envoi.

        Appelé après l'insertion des `messages` et **avant** la journalisation, afin
        que le log reflète exactement ce qui part sur le réseau. L'implémentation par
        défaut ne touche à rien.

        Args:
            params: Paramètres fusionnés, `messages` inclus.

        Returns:
            Les paramètres effectivement envoyés au provider.
        """
        return params

    # ------------------------------------------------------------------
    # Chemin texte
    # ------------------------------------------------------------------

    def request(
        self,
        system_prompt: str,
        user_instruction: str,
        config: LLMConfig[UserData, Data] | None = None,
        logger: Logger | None = None,
    ) -> LLMResponse:
        """Envoie une complétion texte et rend la réponse normalisée.

        Args:
            system_prompt: Prompt système.
            user_instruction: Contenu utilisateur.
            config: Configuration ponctuelle, fusionnée avec celle du client.
            logger: Journal d'échange. Si fourni, en-tête, prompts et réponse y sont écrits.

        Returns:
            La réponse du provider normalisée en `LLMResponse`.

        Raises:
            Exception: Toute erreur du SDK est journalisée puis propagée telle quelle.
        """
        try:
            merged_config = self._prepare_params(config)
            merged_config["messages"] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_instruction},
            ]
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
            return parsed_response

        except Exception as e:
            if logger:
                logger.error(f"Error during LLM API request: {e}", exc_info=e)
            raise e

    # ------------------------------------------------------------------
    # Journalisation
    # ------------------------------------------------------------------

    @staticmethod
    def write_header(
        logger: logging.Logger,
        context: str | None,
        parameters: Mapping[str, Any],
    ) -> None:
        """Écrit l'en-tête de requête dans le journal d'échange.

        Args:
            logger: Journal d'échange.
            parameters: Paramètres envoyés à l'API (`messages` est écarté).
            context: Libellé optionnel (par exemple `"chunk_042"`).
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
    def write_prompt(logger: logging.Logger, parameters: Mapping[str, Any]) -> None:
        """Journalise les messages envoyés au LLM.

        `parameters` est volontairement typé `Mapping` et non `Data` : le hook
        `completion:kwargs` d'instructor fournit un `dict[str, Any]` brut.
        """
        messages: list[Mapping[str, Any]] = parameters.get("messages", [])
        logger.info("\n=== MESSAGES ===")
        for msg in messages:
            role = str(msg.get("role", "unknown")).upper()
            content = msg.get("content", "NO CONTENT")
            logger.info(f"\n--- {role} ---\n{content}")

    def write_response(
        self,
        logger: logging.Logger,
        response: LLMResponse,
    ) -> None:
        """Journalise la réponse du LLM, raisonnement et appels d'outils compris.

        Args:
            logger: Journal d'échange.
            response: Réponse normalisée à écrire.
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
