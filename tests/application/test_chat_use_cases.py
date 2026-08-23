from collections.abc import (
    AsyncIterator,
)
from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.application.chat.ask import (
    AskQuestion,
    IndexNotReadyError,
)
from ducktective.application.chat.manage import (
    DeleteConversation,
    ListConversations,
    ReadConversation,
    StartConversation,
)
from ducktective.application.chat.views import (
    ConversationView,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.core.chat.ports import (
    ChatRequest,
)
from ducktective.core.chat.value_objects import (
    ChatEvent,
    ChatEventKind,
    ChatRole,
    ChatUsage,
    ToolInvocation,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import VcsProvider as VcsProviderKind
from ducktective.core.indexing.entities import (
    IndexSnapshot,
    IndexStats,
)
from ducktective.core.retrieval.navigation import (
    CodeNavigator,
    NavigationAnswer,
    NavigationSource,
    ReferenceRelation,
)
from ducktective.core.types import (
    CommitSha,
    ConversationId,
    RepositoryId,
    TenantId,
)
from tests.fakes import (
    FakeEventPublisher,
    FakeUnitOfWork,
)


HEAD_SHA = CommitSha("c" * 40)


class ScriptedAgent:
    """Агент, отдающий заранее заданные события."""

    def __init__(self, events: list[ChatEvent]) -> None:
        self.events = events
        self.requests: list[ChatRequest] = []

    async def answer(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        self.requests.append(request)
        for event in self.events:
            yield event


class FailingAgent:
    """Агент, отказавший посреди ответа."""

    def __init__(self, before_failure: list[ChatEvent]) -> None:
        self._before_failure = before_failure

    async def answer(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        for event in self._before_failure:
            yield event
        raise RuntimeError("модель отвалилась")


class SilentNavigator:
    """Навигатор, которому в этих тестах отвечать нечем."""

    source = NavigationSource.INDEX

    async def search_code(self, query: str, *, limit: int = 10) -> NavigationAnswer:
        return NavigationAnswer(source=NavigationSource.INDEX)

    async def get_definition(self, name: str, *, limit: int = 5) -> NavigationAnswer:
        return NavigationAnswer(source=NavigationSource.INDEX)

    async def find_callers(self, name: str, *, limit: int = 20) -> NavigationAnswer:
        return NavigationAnswer(source=NavigationSource.INDEX)

    async def find_references(
        self,
        name: str,
        *,
        relation: ReferenceRelation = ReferenceRelation.ANY,
        limit: int = 20,
    ) -> NavigationAnswer:
        return NavigationAnswer(source=NavigationSource.INDEX)

    async def get_file_context(
        self,
        path: str,
        *,
        start_line: int,
        end_line: int,
        limit: int = 10,
    ) -> NavigationAnswer:
        return NavigationAnswer(source=NavigationSource.INDEX)

    async def list_files(self, pattern: str, *, limit: int = 40) -> NavigationAnswer:
        return NavigationAnswer(source=NavigationSource.INDEX)


class SilentNavigators:
    """Фабрика навигаторов: помнит, о каком репозитории спрашивали."""

    def __init__(self) -> None:
        self.asked_for: list[RepositoryId] = []

    def for_repository(self, repository_id: RepositoryId) -> CodeNavigator:
        self.asked_for.append(repository_id)
        return SilentNavigator()


def prepare(
    unit_of_work: FakeUnitOfWork, *, with_index: bool = True
) -> tuple[TenantId, RepositoryId]:
    tenant_id = TenantId(uuid4())
    repository = CodeRepository.register(
        tenant_id=tenant_id,
        name="sandbox",
        vcs_provider=VcsProviderKind.LOCAL,
        local_path=Path("/repos/sandbox"),
    )
    repository.pull_events()
    unit_of_work.code_repositories.add(repository)

    if with_index:
        snapshot = IndexSnapshot.create(repository_id=repository.id, commit_sha=HEAD_SHA)
        snapshot.mark_running()
        snapshot.mark_ready(IndexStats(files_total=3, chunks=9))
        snapshot.pull_events()
        unit_of_work.index_snapshots.add(snapshot)

    return tenant_id, repository.id


async def start(
    unit_of_work: FakeUnitOfWork,
    tenant_id: TenantId,
    repository_id: RepositoryId,
) -> ConversationView:
    started = await StartConversation(unit_of_work, FakeEventPublisher()).execute(
        tenant_id,
        repository_id,
    )
    return started.conversation


async def test_conversation_starts_empty_and_untitled() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)

    view = await start(unit_of_work, tenant_id, repository_id)

    assert view.title == ""
    assert view.message_count == 0


async def test_conversation_of_a_foreign_tenant_cannot_be_started() -> None:
    unit_of_work = FakeUnitOfWork()
    _, repository_id = prepare(unit_of_work)

    with pytest.raises(PermissionDeniedError):
        await start(unit_of_work, TenantId(uuid4()), repository_id)


async def test_question_survives_an_answer_that_never_came() -> None:
    """Разговор, потерявший вопрос, выглядит так, будто его не задавали."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    view = await start(unit_of_work, tenant_id, repository_id)

    use_case = AskQuestion(
        unit_of_work,
        FakeEventPublisher(),
        FailingAgent([]),
        SilentNavigators(),
    )
    stream = await use_case.execute(tenant_id, view.id, "где проверяются права?")

    with pytest.raises(RuntimeError):
        async for _ in stream:
            pass

    read = await ReadConversation(unit_of_work).execute(tenant_id, view.id)
    assert [message.role for message in read.messages] == [ChatRole.USER]


async def test_answer_and_what_the_agent_looked_at_are_recorded() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    view = await start(unit_of_work, tenant_id, repository_id)

    invocation = ToolInvocation(call_id="c1", name="search_code", arguments='{"query": "права"}')
    agent = ScriptedAgent(
        [
            ChatEvent(kind=ChatEventKind.TOOL_CALL, tool=invocation),
            ChatEvent(kind=ChatEventKind.TOOL_RESULT, tool=invocation, text="app/perm.py:1-9"),
            ChatEvent(kind=ChatEventKind.TOKEN, text="права "),
            ChatEvent(
                kind=ChatEventKind.ANSWER,
                text="права проверяются в check_pack_access",
                model="fake-model",
                usage=ChatUsage(input_tokens=900, output_tokens=120),
            ),
        ]
    )
    use_case = AskQuestion(unit_of_work, FakeEventPublisher(), agent, SilentNavigators())

    stream = await use_case.execute(tenant_id, view.id, "где проверяются права?")
    async for _ in stream:
        pass

    read = await ReadConversation(unit_of_work).execute(tenant_id, view.id)
    roles = [message.role for message in read.messages]
    assert roles == [ChatRole.USER, ChatRole.ASSISTANT, ChatRole.TOOL, ChatRole.ASSISTANT]
    assert read.messages[-1].tokens_output == 120
    assert read.title == "где проверяются права?"


async def test_answer_is_written_down_before_the_client_sees_it() -> None:
    """Клиент, получив ответ, закрывает сокет и снимает обработчик.

    Запись, начатая после отправки, обрывается на первом же `await`:
    на живом прогоне так терялся весь второй ответ разговора.
    """
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    view = await start(unit_of_work, tenant_id, repository_id)
    agent = ScriptedAgent([ChatEvent(kind=ChatEventKind.ANSWER, text="ответ")])

    stream = await AskQuestion(
        unit_of_work,
        FakeEventPublisher(),
        agent,
        SilentNavigators(),
    ).execute(tenant_id, view.id, "вопрос")

    async for event in stream:
        if event.kind is ChatEventKind.ANSWER:
            read = await ReadConversation(unit_of_work).execute(tenant_id, view.id)
            assert [message.content for message in read.messages][-1] == "ответ"
            break


async def test_agent_is_told_which_revision_the_index_describes() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    view = await start(unit_of_work, tenant_id, repository_id)
    agent = ScriptedAgent([ChatEvent(kind=ChatEventKind.ANSWER, text="ответ")])

    stream = await AskQuestion(
        unit_of_work,
        FakeEventPublisher(),
        agent,
        SilentNavigators(),
    ).execute(tenant_id, view.id, "вопрос")
    async for _ in stream:
        pass

    assert agent.requests[0].index_revision == HEAD_SHA


async def test_repository_without_an_index_cannot_be_talked_about() -> None:
    """Без индекса агенту нечем смотреть в код, и разговор выродился бы в общие слова."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work, with_index=False)
    view = await start(unit_of_work, tenant_id, repository_id)

    with pytest.raises(IndexNotReadyError):
        await AskQuestion(
            unit_of_work,
            FakeEventPublisher(),
            ScriptedAgent([]),
            SilentNavigators(),
        ).execute(tenant_id, view.id, "вопрос")


async def test_second_empty_conversation_is_not_started() -> None:
    """Разговор без вопроса неотличим от такого же соседа.

    Нажатая дважды кнопка оставляла бы вереницу «без вопроса», среди
    которых потом не выбрать нужный.
    """
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    use_case = StartConversation(unit_of_work, FakeEventPublisher())

    first = await use_case.execute(tenant_id, repository_id)
    again = await use_case.execute(tenant_id, repository_id)

    assert first.is_new is True
    assert again.is_new is False
    assert again.conversation.id == first.conversation.id

    listed = await ListConversations(unit_of_work).execute(tenant_id, repository_id)
    assert len(listed) == 1


async def test_conversation_with_a_question_does_not_block_the_next_one() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    use_case = StartConversation(unit_of_work, FakeEventPublisher())
    started = await use_case.execute(tenant_id, repository_id)

    stream = await AskQuestion(
        unit_of_work,
        FakeEventPublisher(),
        ScriptedAgent([ChatEvent(kind=ChatEventKind.ANSWER, text="ответ")]),
        SilentNavigators(),
    ).execute(tenant_id, started.conversation.id, "вопрос")
    async for _ in stream:
        pass

    again = await use_case.execute(tenant_id, repository_id)

    assert again.is_new is True
    assert again.conversation.id != started.conversation.id


async def test_empty_conversation_of_another_repository_is_not_reused() -> None:
    """Разговор опирается на индекс своего репозитория и переехать не может."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    other = CodeRepository.register(
        tenant_id=tenant_id,
        name="другой",
        vcs_provider=VcsProviderKind.LOCAL,
        local_path=Path("/repos/other"),
    )
    other.pull_events()
    unit_of_work.code_repositories.add(other)
    use_case = StartConversation(unit_of_work, FakeEventPublisher())

    first = await use_case.execute(tenant_id, repository_id)
    second = await use_case.execute(tenant_id, other.id)

    assert second.is_new is True
    assert second.conversation.id != first.conversation.id


async def test_conversations_are_listed_freshest_first() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    older = await start(unit_of_work, tenant_id, repository_id)
    stream = await AskQuestion(
        unit_of_work,
        FakeEventPublisher(),
        ScriptedAgent([ChatEvent(kind=ChatEventKind.ANSWER, text="ответ")]),
        SilentNavigators(),
    ).execute(tenant_id, older.id, "вопрос")
    async for _ in stream:
        pass
    newer = await start(unit_of_work, tenant_id, repository_id)

    listed = await ListConversations(unit_of_work).execute(tenant_id, repository_id)

    assert [view.id for view in listed][:2] == [newer.id, older.id]
    assert all(view.messages == () for view in listed)


async def test_foreign_conversation_is_not_readable() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    view = await start(unit_of_work, tenant_id, repository_id)

    with pytest.raises(PermissionDeniedError):
        await ReadConversation(unit_of_work).execute(TenantId(uuid4()), view.id)


async def test_deleted_conversation_is_gone() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    view = await start(unit_of_work, tenant_id, repository_id)

    await DeleteConversation(unit_of_work, FakeEventPublisher()).execute(tenant_id, view.id)

    listed = await ListConversations(unit_of_work).execute(tenant_id, repository_id)
    assert [item.id for item in listed] == []
    assert ConversationId(view.id) not in {item.id for item in listed}
