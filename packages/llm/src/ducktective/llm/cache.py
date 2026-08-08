import hashlib
import json
from collections.abc import (
    Sequence,
)
from typing import (
    Any,
)

from redis.asyncio import (
    Redis,
)

from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmResponse,
    LlmUsage,
    ModelRequirements,
    ToolCall,
    ToolSpec,
)


CACHE_KEY_PREFIX = "ducktective:llm"
DEFAULT_TTL_SECONDS = 7 * 24 * 3600


def build_cache_key(
    *,
    model: str,
    messages: list[LlmMessage],
    requirements: ModelRequirements,
    prompt_version: str,
    tools: Sequence[ToolSpec] | None = None,
) -> str:
    """Ключ ответа по содержимому запроса.

    Перечень инструментов входит в ключ наравне с сообщениями: один и тот же
    диалог с инструментами и без них — два разных вопроса, и подменить один
    ответ другим значит выдать за ответ модели то, чего она не говорила.
    """
    payload = json.dumps(
        {
            "prompt_version": prompt_version,
            "model": model,
            "temperature": requirements.temperature,
            "max_output_tokens": requirements.max_output_tokens,
            "messages": [_message_key_part(message) for message in messages],
            "tools": [tool.name for tool in tools or ()],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{CACHE_KEY_PREFIX}:{digest}"


def _message_key_part(message: LlmMessage) -> dict[str, Any]:
    return {
        "role": message.role.value,
        "content": message.content,
        "tool_calls": [_call_payload(call) for call in message.tool_calls],
        "tool_call_id": message.tool_call_id,
    }


def _call_payload(call: ToolCall) -> dict[str, str]:
    return {"id": call.id, "name": call.name, "arguments": call.arguments}


class RedisResponseCache:
    """Кэш ответов модели.

    Повторный прогон того же диффа при отладке промптов и регрессионные прогоны
    не должны стоить денег и времени.
    """

    def __init__(self, redis_client: Redis, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._redis_client = redis_client
        self._ttl_seconds = ttl_seconds

    async def get(self, cache_key: str) -> LlmResponse | None:
        raw = await self._redis_client.get(cache_key)
        if raw is None:
            return None

        payload = json.loads(raw)
        return LlmResponse(
            content=payload["content"],
            model=payload["model"],
            provider=payload["provider"],
            usage=LlmUsage(**payload["usage"]),
            latency_ms=payload["latency_ms"],
            is_cache_hit=True,
            tool_calls=tuple(ToolCall(**call) for call in payload.get("tool_calls", ())),
        )

    async def put(self, cache_key: str, response: LlmResponse) -> None:
        payload = json.dumps(
            {
                "content": response.content,
                "model": response.model,
                "provider": response.provider,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "cost_usd": response.usage.cost_usd,
                },
                "latency_ms": response.latency_ms,
                "tool_calls": [_call_payload(call) for call in response.tool_calls],
            },
            ensure_ascii=False,
        )
        await self._redis_client.set(cache_key, payload, ex=self._ttl_seconds)
