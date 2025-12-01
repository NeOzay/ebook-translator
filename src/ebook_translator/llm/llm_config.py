from typing import NotRequired, TypedDict


class LLMConfig(TypedDict):
    """Configuration for the LLM client."""

    temperature: NotRequired[float]
    """Sampling temperature for response variability"""

    max_tokens: NotRequired[int]
    """Maximum number of tokens in the response"""

    top_p: NotRequired[float]
    """Nucleus sampling parameter"""

    use_reasoning: NotRequired[bool]
    """Whether to enable reasoning capabilities"""

    use_json_mode: NotRequired[bool]
    """Whether to use JSON mode for structured responses"""
