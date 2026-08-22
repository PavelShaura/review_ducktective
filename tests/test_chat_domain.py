from uuid import (
    uuid4,
)

import pytest

from ducktective.core.chat.entities import (
    MAX_QUESTION_LENGTH,
    Conversation,
)
from ducktective.core.chat.events import (
    ConversationStarted,
)
from ducktective.core.chat.value_objects import (
    ChatRole,
    ChatUsage,
    ToolInvocation,
)
from ducktective.core.exceptions import (
    InvariantViolationError,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)


TENANT_ID = TenantId(uuid4())
REPOSITORY_ID = RepositoryId(uuid4())


def build_conversation() -> Conversation:
    return Conversation.start(tenant_id=TENANT_ID, repository_id=REPOSITORY_ID)


def test_started_conversation_announces_itself() -> None:
    conversation = build_conversation()

    events = conversation.pull_events()

    assert any(isinstance(event, ConversationStarted) for event in events)


def test_first_question_becomes_the_title() -> None:
    """Заголовок не спрашивается: до первого вопроса его неоткуда взять."""
    conversation = build_conversation()

    conversation.ask("где проверяются права на пак?")

    assert conversation.title == "где проверяются права на пак?"


def test_later_questions_keep_the_title() -> None:
    conversation = build_conversation()
    conversation.ask("где проверяются права?")

    conversation.ask("а кто это вызывает?")

    assert conversation.title == "где проверяются права?"


@pytest.mark.parametrize("question", ["", "   ", "\n"])
def test_empty_question_is_refused(question: str) -> None:
    conversation = build_conversation()

    with pytest.raises(InvariantViolationError):
        conversation.ask(question)


def test_question_longer_than_the_window_is_refused() -> None:
    """Файл, вставленный в поле ввода, съел бы всё место под ответ."""
    conversation = build_conversation()

    with pytest.raises(InvariantViolationError):
        conversation.ask("x" * (MAX_QUESTION_LENGTH + 1))


def test_what_the_agent_looked_at_stays_in_the_conversation() -> None:
    """Открытая заново беседа иначе показывает выводы без источников."""
    conversation = build_conversation()
    conversation.ask("кто вызывает build_total?")
    invocation = ToolInvocation(call_id="call_1", name="find_callers", arguments='{"name": "x"}')

    conversation.record_tool_call((invocation,))
    conversation.record_tool_result(invocation, "Определение — app/report.py:10-20")
    conversation.record_answer("Вызывает ReportBuilder", model="lm_studio/gemma")

    roles = [message.role for message in conversation.messages]
    assert roles == [ChatRole.USER, ChatRole.ASSISTANT, ChatRole.TOOL, ChatRole.ASSISTANT]
    assert conversation.messages[1].tool_calls == (invocation,)
    assert conversation.messages[2].tool_name == "find_callers"


def test_answer_carries_the_model_and_its_cost() -> None:
    conversation = build_conversation()
    conversation.ask("что это за модуль?")

    conversation.record_answer(
        "Модуль про отчёты",
        model="lm_studio/gemma",
        usage=ChatUsage(input_tokens=1200, output_tokens=300),
    )

    answer = conversation.messages[-1]
    assert answer.is_answer
    assert answer.model == "lm_studio/gemma"
    assert answer.usage.output_tokens == 300


def test_conversation_remembers_when_it_last_moved() -> None:
    conversation = build_conversation()
    started_at = conversation.updated_at

    conversation.ask("вопрос")

    assert conversation.updated_at > started_at
