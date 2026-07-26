from dataclasses import (
    dataclass,
    field,
)
from enum import (
    StrEnum,
)


class LlmRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, kw_only=True)
class LlmMessage:
    role: LlmRole
    content: str


@dataclass(frozen=True, kw_only=True)
class ModelRequirements:
    """Требования узла к модели.

    Роутер выбирает провайдера по этим требованиям и политике репозитория:
    при запрете облака дешёвая локальная модель используется даже там, где
    качество будет ниже.
    """

    needs_deep_reasoning: bool = False
    cloud_allowed: bool = False
    max_output_tokens: int = 4096
    temperature: float = 0.0


@dataclass(frozen=True, kw_only=True)
class LlmUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True, kw_only=True)
class LlmResponse:
    content: str
    model: str
    provider: str
    usage: LlmUsage = field(default_factory=LlmUsage)
    latency_ms: int = 0
    is_cache_hit: bool = False
