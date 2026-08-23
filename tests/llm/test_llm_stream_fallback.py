from collections.abc import (
    AsyncIterator,
)
from types import (
    SimpleNamespace,
)
from typing import (
    Any,
)

import pytest
from litellm.exceptions import (
    RateLimitError,
)

from ducktective.core.code_repository.value_objects import (
    ModelTrust,
)
from ducktective.core.exceptions import (
    LlmInvocationError,
    LlmRateLimitError,
)
from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmRole,
    ModelRequirements,
)
from ducktective.llm.client import (
    LiteLlmClient,
)
from ducktective.llm.router import (
    ModelChoice,
    ModelRouter,
)


FREE = ModelChoice(
    name="free",
    model="openai/big-pickle",
    provider="openai",
    api_key="secret",
    trust=ModelTrust.TRAINING_REMOTE,
)
LOCAL = ModelChoice(name="local", model="lm_studio/qwen", provider="lm_studio")

QUESTION = [LlmMessage(role=LlmRole.USER, content="как работает чат?")]
ALLOW_FREE = ModelRequirements(
    allowed_trust=ModelTrust.TRAINING_REMOTE,
    preferred_model="free",
)


def build_client(behaviour: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> LiteLlmClient:
    """Клиент, у которого поведение каждой модели задано наперёд.

    Подмена снимается вместе с тестом: `litellm` живёт модулем на процесс,
    и оставленная заглушка досталась бы соседям по прогону.
    """
    router = ModelRouter(
        local_choice=LOCAL,
        remote_choices=(FREE,),
        remote_enabled=True,
    )

    async def fake_completion(**payload: Any) -> Any:
        return _stream(behaviour[payload["model"]])

    monkeypatch.setattr("ducktective.llm.client.litellm.acompletion", fake_completion)
    return LiteLlmClient(router)


async def _stream(script: Any) -> AsyncIterator[Any]:
    for step in script:
        if isinstance(step, Exception):
            raise step
        yield _chunk(step)


def _chunk(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=text, tool_calls=None), finish_reason=None
            )
        ],
        usage=None,
        model="fake",
    )


def rate_limit() -> RateLimitError:
    return RateLimitError(message="Rate limit exceeded", llm_provider="openai", model="big-pickle")


async def collect(client: LiteLlmClient, requirements: ModelRequirements) -> str:
    answer = ""
    async for piece in client.stream(QUESTION, requirements=requirements):
        if piece.text:
            answer += piece.text
    return answer


async def notices(client: LiteLlmClient, requirements: ModelRequirements) -> list[str]:
    collected: list[str] = []
    async for piece in client.stream(QUESTION, requirements=requirements):
        if piece.notice:
            collected.append(piece.notice)
    return collected


async def test_exhausted_free_tier_hands_the_answer_to_the_next_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Вторая модель заведена ровно для этой минуты: лимит — не поломка."""
    client = build_client(
        {
            "openai/big-pickle": [rate_limit()],
            "lm_studio/qwen": ["ответ ", "локальной"],
        },
        monkeypatch,
    )

    assert await collect(client, ALLOW_FREE) == "ответ локальной"


async def test_answer_already_started_is_not_rewritten_by_another_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Повтор писал бы другой текст поверх показанного — поток обрывается."""
    client = build_client(
        {
            "openai/big-pickle": ["начало ", rate_limit()],
            "lm_studio/qwen": ["целый ответ"],
        },
        monkeypatch,
    )

    with pytest.raises(LlmInvocationError):
        await collect(client, ALLOW_FREE)


async def test_last_refusal_explains_what_to_do(monkeypatch: pytest.MonkeyPatch) -> None:
    """Исключение библиотеки человеку ничего не говорит, а совет — говорит."""
    client = build_client(
        {
            "openai/big-pickle": [rate_limit()],
            "lm_studio/qwen": [rate_limit()],
        },
        monkeypatch,
    )

    with pytest.raises(LlmRateLimitError) as failure:
        await collect(client, ALLOW_FREE)

    assert "лимит запросов" in str(failure.value)
    assert "другую модель" in str(failure.value)


async def test_replacement_is_announced_before_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Подменить исполнителя молча нельзя: модель выбирал человек."""
    client = build_client(
        {
            "openai/big-pickle": [rate_limit()],
            "lm_studio/qwen": ["ответ"],
        },
        monkeypatch,
    )

    announced = await notices(client, ALLOW_FREE)

    assert len(announced) == 1
    assert "free" in announced[0]
    assert "исчерпан лимит запросов" in announced[0]
    assert "local" in announced[0]


async def test_answer_without_replacement_says_nothing_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = build_client({"openai/big-pickle": ["ответ"]}, monkeypatch)

    assert await notices(client, ALLOW_FREE) == []


async def test_refused_model_is_not_asked_again_within_the_same_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Цикл тратит по обращению на шаг, и стучаться в исчерпанную каждый раз —
    значит платить её отказом за каждый шаг разговора."""
    asked: list[str] = []

    async def fake_completion(**payload: Any) -> Any:
        asked.append(payload["model"])
        if payload["model"] == "openai/big-pickle":
            return _stream([rate_limit()])
        return _stream(["ответ"])

    monkeypatch.setattr("ducktective.llm.client.litellm.acompletion", fake_completion)
    client = LiteLlmClient(
        ModelRouter(local_choice=LOCAL, remote_choices=(FREE,), remote_enabled=True)
    )

    await collect(client, ALLOW_FREE)
    await collect(client, ALLOW_FREE)

    assert asked.count("openai/big-pickle") == 1
    assert asked.count("lm_studio/qwen") == 2
