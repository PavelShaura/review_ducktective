import json
from types import (
    SimpleNamespace,
)

from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmResponse,
    LlmRole,
    ModelRequirements,
    ToolCall,
    ToolSpec,
)
from ducktective.llm.cache import (
    RedisResponseCache,
    build_cache_key,
)
from ducktective.llm.client import (
    _build_response,
    _read_tool_calls,
    _to_wire,
)
from ducktective.llm.router import (
    ModelChoice,
)


SEARCH_TOOL = ToolSpec(
    name="search_code",
    description="Ищет фрагменты кода",
    parameters={"type": "object", "properties": {"query": {"type": "string"}}},
)


def _completion(tool_calls: list[SimpleNamespace] | None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="", tool_calls=tool_calls),
                finish_reason="tool_calls",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
    )


def _raw_call(
    call_id: str = "call_1", arguments: str = '{"query": "add_finding"}'
) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name="search_code", arguments=arguments),
    )


def test_tool_calls_reach_the_response() -> None:
    choice = ModelChoice(name="local", model="lm_studio/qwen", provider="lm_studio")

    response = _build_response(_completion([_raw_call()]), choice, 10)

    assert response.has_tool_calls
    assert response.tool_calls[0].name == "search_code"
    assert response.tool_calls[0].arguments == '{"query": "add_finding"}'


def test_answer_without_calls_has_none() -> None:
    choice = ModelChoice(name="local", model="lm_studio/qwen", provider="lm_studio")

    assert not _build_response(_completion(None), choice, 10).has_tool_calls


def test_broken_arguments_survive_until_execution() -> None:
    """Неразобранный JSON — ответ модели, а не сбой обращения к ней.

    Исполнитель вернёт ошибку результатом вызова, и модель повторит его.
    Упавший на разборе клиент такого шанса не даёт.
    """
    calls = _read_tool_calls(
        SimpleNamespace(tool_calls=[_raw_call(arguments='{"query": "add_fin')])
    )

    assert calls[0].arguments == '{"query": "add_fin'


def test_call_without_identifier_gets_one() -> None:
    raw = SimpleNamespace(id=None, function=SimpleNamespace(name="search_code", arguments="{}"))

    calls = _read_tool_calls(SimpleNamespace(tool_calls=[raw]))

    assert calls[0].id


def test_assistant_message_carries_its_calls_back() -> None:
    """Провайдер сверяет пары «вызов — результат» и отвергает переписку без вызова."""
    message = LlmMessage(
        role=LlmRole.ASSISTANT,
        content="",
        tool_calls=(ToolCall(id="call_1", name="search_code", arguments="{}"),),
    )

    wire = _to_wire(message)

    assert wire["tool_calls"] == [
        {"id": "call_1", "type": "function", "function": {"name": "search_code", "arguments": "{}"}}
    ]


def test_tool_result_names_the_call_it_answers() -> None:
    message = LlmMessage(role=LlmRole.TOOL, content="нашлось три места", tool_call_id="call_1")

    wire = _to_wire(message)

    assert wire["role"] == "tool"
    assert wire["tool_call_id"] == "call_1"


def test_plain_message_stays_plain() -> None:
    wire = _to_wire(LlmMessage(role=LlmRole.USER, content="привет"))

    assert wire == {"role": "user", "content": "привет"}


def _key(**overrides: object) -> str:
    arguments: dict[str, object] = {
        "model": "lm_studio/qwen",
        "messages": [LlmMessage(role=LlmRole.USER, content="дифф")],
        "requirements": ModelRequirements(),
        "prompt_version": "v1",
    }
    arguments.update(overrides)
    return build_cache_key(**arguments)  # type: ignore[arg-type]


def test_tools_change_the_cache_key() -> None:
    """Один диалог с инструментами и без них — два разных вопроса."""
    assert _key() != _key(tools=[SEARCH_TOOL])


def test_calls_in_the_transcript_change_the_cache_key() -> None:
    with_call = [
        LlmMessage(
            role=LlmRole.ASSISTANT,
            content="",
            tool_calls=(ToolCall(id="call_1", name="search_code", arguments="{}"),),
        )
    ]

    assert _key() != _key(messages=with_call)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value


async def test_cached_answer_keeps_its_calls() -> None:
    """Ответ из кэша без вызовов остановил бы цикл на середине расследования."""
    redis = FakeRedis()
    cache = RedisResponseCache(redis)  # type: ignore[arg-type]
    response = LlmResponse(
        content="",
        model="lm_studio/qwen",
        provider="lm_studio",
        tool_calls=(ToolCall(id="call_1", name="search_code", arguments='{"query": "x"}'),),
    )

    await cache.put("k", response)
    restored = await cache.get("k")

    assert restored is not None
    assert restored.tool_calls == response.tool_calls
    assert json.loads(redis.values["k"])["tool_calls"][0]["name"] == "search_code"
