import hashlib
import json

from redis.asyncio import (
    Redis,
)

from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmResponse,
    LlmUsage,
    ModelRequirements,
)


CACHE_KEY_PREFIX = "ducktective:llm"
DEFAULT_TTL_SECONDS = 7 * 24 * 3600


def build_cache_key(
    *,
    model: str,
    messages: list[LlmMessage],
    requirements: ModelRequirements,
    prompt_version: str,
) -> str:
    payload = json.dumps(
        {
            "prompt_version": prompt_version,
            "model": model,
            "temperature": requirements.temperature,
            "max_output_tokens": requirements.max_output_tokens,
            "messages": [
                {"role": message.role.value, "content": message.content} for message in messages
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{CACHE_KEY_PREFIX}:{digest}"


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
            },
            ensure_ascii=False,
        )
        await self._redis_client.set(cache_key, payload, ex=self._ttl_seconds)
