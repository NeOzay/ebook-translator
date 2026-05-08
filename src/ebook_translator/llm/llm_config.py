from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
)

from openai.types.chat import (
    ChatCompletionMessageToolCallUnion,
)
from typing_extensions import TypedDict

from template.types import ConvertibleModel

if TYPE_CHECKING:
    from ebook_translator.llm.clients.client import ClientProviderProtocol


@dataclass(kw_only=True)
class GenericLLMConfig:
    """Kwargs utilisateur génériques, à adapter selon les besoins spécifiques de chaque provider. Ces kwargs sont ceux que l'utilisateur final peut fournir, tandis que les BaseKwargs incluent les champs requis par le provider."""

    temperature: float | None = field(default=None)  # défaut 1.0, plage [0, 2]
    top_p: float | None = field(default=None)  # défaut 1.0, plage (0, 1]
    use_thinking: bool | Literal["low", "high", "max"] | None = field(default=None)
    max_tokens: int | None = field(default=None)


@dataclass(kw_only=True)
class JsonRequestConfig[M: ConvertibleModel[Any]]:
    config: LLMConfig | ClientProviderProtocol | None = field(default=None)
    response_model: type[M]


class UserKwargs(TypedDict, total=False):
    pass


class FullKwargs(UserKwargs, extra_items=Any):
    # ---- Requis ----
    model: str
    # messages: Iterable[ChatCompletionMessageParam]


class StreamOptions(TypedDict, total=False):
    include_usage: bool


class ResponseFormatText(TypedDict):
    type: Literal["text"]


class ResponseFormatJSONObject(TypedDict):
    type: Literal["json_object"]


type ResponseFormat = ResponseFormatText | ResponseFormatJSONObject


@dataclass
class LLMConfigExport[F: FullKwargs = FullKwargs]:
    properties: F
    provider: type[ClientProviderProtocol[Any, F]]

    def get_properties(
        self,
        provider: ClientProviderProtocol[Any, F] | type[ClientProviderProtocol[Any, F]],
    ) -> F:
        if not isinstance(provider, type):
            provider = provider.__class__
        if self.provider != provider:
            raise ValueError(
                f"Provider mismatch: expected {self.provider}, got {provider}"
            )
        return self.properties


type LLMConfig[U: UserKwargs = UserKwargs, D: FullKwargs = FullKwargs] = (
    LLMConfigExport[D] | U | GenericLLMConfig
)


@dataclass
class LLMResponse:
    content: str | None
    reasoning: str | None
    tool_calls: list[ChatCompletionMessageToolCallUnion] | None
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    reasoning_tokens: int
    model: str
    response_id: str
