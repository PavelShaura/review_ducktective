from collections.abc import (
    AsyncIterator,
    Sequence,
)
from dataclasses import (
    replace,
)
from datetime import (
    UTC,
    datetime,
)
from typing import (
    Any,
)
from uuid import (
    uuid4,
)

from ducktective.core.chat.entities import (
    AttachedDocument,
)
from ducktective.core.chat.ports import (
    ChatRequest,
)
from ducktective.core.chat.value_objects import (
    ChatEventKind,
)
from ducktective.core.exceptions import (
    LlmContextOverflowError,
)
from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmResponse,
    LlmStreamPiece,
    LlmUsage,
    ModelRequirements,
    ToolCall,
    ToolSpec,
)
from ducktective.core.retrieval.navigation import (
    CodeFragment,
    NavigationAnswer,
    NavigationSource,
    ReferenceRelation,
)
from ducktective.core.types import (
    CommitSha,
    RepositoryId,
)
from ducktective.llm.chat_agent import (
    AgenticChatAgent,
    PresetChatAgent,
)
from tests.fakes import (
    StubNavigator,
)


REPOSITORY_ID = RepositoryId(uuid4())


class StreamingLlmClient:
    """Модель, отдающая заранее заданные ходы по одному на обращение."""

    def __init__(self, turns: list[tuple[str, tuple[ToolCall, ...]]]) -> None:
        self._turns = turns
        self.calls: list[list[LlmMessage]] = []
        self.offered_tools: list[tuple[str, ...]] = []
        self.overflow_at: int | None = None

    async def complete(self, *args: Any, **kwargs: Any) -> LlmResponse:
        raise AssertionError("Разговор ходит только потоком")

    async def stream(
        self,
        messages: list[LlmMessage],
        *,
        requirements: ModelRequirements,
        tools: Sequence[ToolSpec] | None = None,
    ) -> AsyncIterator[LlmStreamPiece]:
        index = len(self.calls)
        self.calls.append(list(messages))
        self.offered_tools.append(tuple(tool.name for tool in tools or ()))

        if self.overflow_at == index:
            raise LlmContextOverflowError("не поместилось", model="fake-model")

        text, calls = self._turns[min(index, len(self._turns) - 1)]
        for word in text.split(" "):
            yield LlmStreamPiece(text=f"{word} ")

        yield LlmStreamPiece(
            response=LlmResponse(
                content=text,
                model="fake-model",
                provider="fake",
                usage=LlmUsage(input_tokens=100, output_tokens=20),
                tool_calls=calls,
            )
        )


class FakeNavigator(StubNavigator):
    """Навигатор, отвечающий одним и тем же фрагментом."""

    source = NavigationSource.INDEX

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []

    async def search_code(self, query: str, *, limit: int = 10) -> NavigationAnswer:
        self.asked.append(("search_code", query))
        return self._answer()

    async def get_definition(self, name: str, *, limit: int = 5) -> NavigationAnswer:
        self.asked.append(("get_definition", name))
        return self._answer()

    async def find_callers(self, name: str, *, limit: int = 20) -> NavigationAnswer:
        self.asked.append(("find_callers", name))
        return self._answer()

    async def find_references(
        self,
        name: str,
        *,
        relation: ReferenceRelation = ReferenceRelation.ANY,
        limit: int = 20,
    ) -> NavigationAnswer:
        self.asked.append(("find_references", name))
        return self._answer()

    async def get_file_context(
        self,
        path: str,
        *,
        start_line: int,
        end_line: int,
        limit: int = 10,
    ) -> NavigationAnswer:
        self.asked.append(("get_file_context", path))
        return self._answer()

    async def list_files(self, pattern: str, *, limit: int = 40) -> NavigationAnswer:
        self.asked.append(("list_files", pattern))
        return NavigationAnswer(source=NavigationSource.INDEX, note=f"Файлы по «{pattern}»")

    def _answer(self) -> NavigationAnswer:
        return NavigationAnswer(
            source=NavigationSource.INDEX,
            fragments=(
                CodeFragment(
                    path="app/permissions.py",
                    start_line=10,
                    end_line=20,
                    text="def check_pack_access(user, pack): ...",
                    title="check_pack_access",
                ),
            ),
        )


def build_request(
    *,
    navigator: FakeNavigator | None = None,
    revision: str | None = None,
) -> ChatRequest:
    return ChatRequest(
        repository_id=REPOSITORY_ID,
        question="где проверяются права на пак?",
        requirements=ModelRequirements(),
        navigator=navigator,
        index_revision=CommitSha(revision) if revision else None,
    )


async def collect(agent: Any, request: ChatRequest) -> list[Any]:
    return [event async for event in agent.answer(request)]


async def test_answer_arrives_in_pieces_before_it_is_finished() -> None:
    """Локальная модель пишет ответ десятками секунд: ждать целиком нельзя."""
    client = StreamingLlmClient([("права проверяются в check_pack_access", ())])
    agent = AgenticChatAgent(client, fallback=PresetChatAgent(client))

    events = await collect(agent, build_request(navigator=FakeNavigator()))

    tokens = [event for event in events if event.kind is ChatEventKind.TOKEN]
    assert len(tokens) > 1
    assert events[-1].kind is ChatEventKind.ANSWER
    assert events[-1].text.strip() == "права проверяются в check_pack_access"


async def test_agent_looks_into_the_codebase_before_answering() -> None:
    navigator = FakeNavigator()
    client = StreamingLlmClient(
        [
            (
                "посмотрю, где это",
                (ToolCall(id="c1", name="search_code", arguments='{"query": "права"}'),),
            ),
            ("права проверяются в check_pack_access", ()),
        ]
    )
    agent = AgenticChatAgent(client, fallback=PresetChatAgent(client))

    events = await collect(agent, build_request(navigator=navigator))

    kinds = [event.kind for event in events]
    assert ChatEventKind.TOOL_CALL in kinds
    assert ChatEventKind.TOOL_RESULT in kinds
    assert navigator.asked == [("search_code", "права")]


async def test_last_step_is_asked_without_tools() -> None:
    """Иначе цикл не кончается: модель просит инструменты бесконечно."""
    client = StreamingLlmClient(
        [("ищу", (ToolCall(id="c1", name="search_code", arguments='{"query": "x"}'),))]
    )
    agent = AgenticChatAgent(client, fallback=PresetChatAgent(client), max_steps=3)

    await collect(agent, build_request(navigator=FakeNavigator()))

    assert client.offered_tools[-1] == ()


async def test_revision_of_the_index_is_said_out_loud() -> None:
    """Индекс описывает зафиксированную ревизию, и об этом нужно сказать."""
    client = StreamingLlmClient([("ответ", ())])
    agent = AgenticChatAgent(client, fallback=PresetChatAgent(client))

    events = await collect(agent, build_request(navigator=FakeNavigator(), revision="cd4278a0" * 5))

    assert events[0].kind is ChatEventKind.NOTE
    assert "cd4278a0" in events[0].text


async def test_conversation_that_outgrew_the_window_falls_back_to_one_search() -> None:
    """Падение было бы хуже: ответ по одному поиску всё же ответ по коду."""
    navigator = FakeNavigator()
    client = StreamingLlmClient([("ответ по преднабору", ())])
    client.overflow_at = 0
    agent = AgenticChatAgent(client, fallback=PresetChatAgent(client))

    events = await collect(agent, build_request(navigator=navigator))

    assert events[-1].kind is ChatEventKind.ANSWER
    assert navigator.asked == [("search_code", "где проверяются права на пак?")]


async def test_preset_agent_puts_the_found_code_into_the_question() -> None:
    navigator = FakeNavigator()
    client = StreamingLlmClient([("ответ", ())])

    await collect(PresetChatAgent(client), build_request(navigator=navigator))

    asked = client.calls[0][-1].content
    assert "где проверяются права на пак?" in asked
    assert "check_pack_access" in asked


async def test_tool_replies_do_not_travel_into_the_next_question() -> None:
    """Найденный фрагмент нужен, пока агент отвечает; потом он занимает окно."""
    client = StreamingLlmClient([("ответ", ())])
    agent = AgenticChatAgent(client, fallback=PresetChatAgent(client))

    await collect(agent, build_request(navigator=FakeNavigator()))

    roles = [message.role.value for message in client.calls[0]]
    assert roles == ["system", "user"]


async def test_answer_that_gives_up_is_sent_back_once() -> None:
    """«Мне потребуется поискать импорты» — это не ответ, а несделанная работа.

    Живой случай: на вопрос про фреймворк бэкенда агент поискал «web framework»,
    ничего не понял и закончил обещанием поискать импорты — при том что импорт
    django лежал в 4949 чанках из 38826.
    """
    client = StreamingLlmClient(
        [
            ("Я не нашёл прямого упоминания. Мне потребуется искать импорты.", ()),
            ("Бэкенд на Django: src/app/apps.py:1-12", ()),
        ]
    )
    agent = AgenticChatAgent(client, fallback=PresetChatAgent(client))

    events = await collect(agent, build_request(navigator=FakeNavigator()))

    assert len(client.calls) == 2
    assert events[-1].kind is ChatEventKind.ANSWER
    assert "Django" in events[-1].text


async def test_the_same_answer_is_not_sent_back_twice() -> None:
    """Переспрос стоит обращения к модели; второй ничего не добавит."""
    client = StreamingLlmClient([("Я не нашёл ничего подходящего.", ())])
    agent = AgenticChatAgent(client, fallback=PresetChatAgent(client))

    events = await collect(agent, build_request(navigator=FakeNavigator()))

    assert len(client.calls) == 2
    assert events[-1].kind is ChatEventKind.ANSWER


async def test_a_finished_answer_goes_out_as_is() -> None:
    client = StreamingLlmClient([("Бэкенд на Django, src/app/apps.py:1-12", ())])
    agent = AgenticChatAgent(client, fallback=PresetChatAgent(client))

    events = await collect(agent, build_request(navigator=FakeNavigator()))

    assert len(client.calls) == 1
    assert events[-1].kind is ChatEventKind.ANSWER


async def test_tool_call_printed_as_text_does_not_reach_the_person() -> None:
    """На последнем шаге инструменты сняты, а модель всё ещё хочет искать.

    Небольшие сборки печатают вызов разметкой прямо в ответ, и человек
    читает служебный мусор как часть объяснения.
    """
    client = StreamingLlmClient(
        [('Проверяю реализацию.\n\n<|tool_call>call:search_code{query:<|"|>close<|"|>}', ())]
    )
    agent = AgenticChatAgent(client, fallback=PresetChatAgent(client), max_steps=1)

    events = await collect(agent, build_request(navigator=FakeNavigator()))

    answer = events[-1]
    assert answer.kind is ChatEventKind.ANSWER
    assert "tool_call" not in answer.text
    assert answer.text == "Проверяю реализацию."


async def test_attached_document_is_announced_before_any_tool_call() -> None:
    """«Предоставьте документ» — ответ чат-бота, а документ уже приложен.

    Перечня инструментов небольшой сборке мало: привычка отвечать так
    сильнее. Имя, размер и начало снимают вопрос до всякого вызова.
    """
    client = StreamingLlmClient([("Документ про внешний API.", ())])
    agent = AgenticChatAgent(client, fallback=PresetChatAgent(client))
    request = build_request(navigator=FakeNavigator())
    request = replace(
        request,
        document=AttachedDocument(
            name="Инструкция по API.txt",
            text="Инструкция по взаимодействию с API\n\nРаздел 1. Авторизация",
            attached_at=datetime.now(UTC),
        ),
    )

    await collect(agent, request)

    system = "\n".join(
        message.content for message in client.calls[0] if message.role.value == "system"
    )
    assert "Инструкция по API.txt" in system
    assert "Раздел 1. Авторизация" in system


async def test_last_turn_is_told_to_answer_with_what_it_has() -> None:
    """«Не хватило шагов» не говорит человеку ничего, чем можно воспользоваться."""
    client = StreamingLlmClient(
        [("ищу", (ToolCall(id="c1", name="search_code", arguments='{"query": "x"}'),))]
    )
    agent = AgenticChatAgent(client, fallback=PresetChatAgent(client), max_steps=2)

    await collect(agent, build_request(navigator=FakeNavigator()))

    last_turn = client.calls[-1]
    assert "last turn" in last_turn[-1].content
    assert client.offered_tools[-1] == ()
