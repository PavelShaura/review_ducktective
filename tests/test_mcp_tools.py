from pathlib import (
    Path,
)
from typing import (
    Any,
)
from uuid import (
    uuid4,
)

from mcp.types import (
    CallToolResult,
    TextContent,
)

from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import (
    VcsProvider,
)
from ducktective.core.indexing.entities import (
    IndexSnapshot,
    IndexStats,
)
from ducktective.core.indexing.value_objects import (
    SymbolKind,
)
from ducktective.core.types import (
    CommitSha,
    TenantId,
)
from ducktective.mcp_server.rendering import (
    MAX_ANSWER_CHARS,
)
from ducktective.mcp_server.runtime import (
    McpRuntime,
)
from ducktective.mcp_server.server import (
    build_server,
)
from ducktective.retrieval.navigation import (
    IndexedNavigators,
)
from tests.fakes import (
    FakeChunkSearch,
    FakeSymbolReader,
    FakeUnitOfWork,
)
from tests.test_retrieval_use_cases import (
    chunk,
    symbol,
)


TENANT_ID = TenantId(uuid4())


def runtime_over(
    unit_of_work: FakeUnitOfWork,
    *,
    symbols: FakeSymbolReader | None = None,
    search: FakeChunkSearch | None = None,
) -> McpRuntime:
    return McpRuntime(
        tenant_id=TENANT_ID,
        unit_of_work=lambda: unit_of_work,
        navigators=IndexedNavigators(
            symbols=symbols or FakeSymbolReader(),
            search=search or FakeChunkSearch(),
        ),
    )


def registered(unit_of_work: FakeUnitOfWork, name: str = "ducktective") -> CodeRepository:
    repository = CodeRepository.register(
        tenant_id=TENANT_ID,
        name=name,
        vcs_provider=VcsProvider.LOCAL,
        local_path=Path(f"/repos/{name}"),
    )
    unit_of_work.code_repositories.add(repository)
    return repository


async def indexed(unit_of_work: FakeUnitOfWork, repository: CodeRepository) -> None:
    snapshot = IndexSnapshot.create(
        repository_id=repository.id,
        commit_sha=CommitSha("a" * 40),
    )
    snapshot.mark_running()
    snapshot.mark_ready(IndexStats(symbols=1))
    async with unit_of_work:
        unit_of_work.index_snapshots.add(snapshot)
        await unit_of_work.commit()


async def call(server: Any, tool: str, /, **arguments: Any) -> str:
    result = await server.call_tool(tool, arguments)
    assert isinstance(result, CallToolResult)
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


async def test_every_documented_tool_is_published() -> None:
    server = build_server(runtime_over(FakeUnitOfWork()))

    published = {tool.name for tool in await server.list_tools()}

    assert published == {
        "list_repositories",
        "search_code",
        "get_definition",
        "find_callers",
        "get_file_context",
    }


async def test_search_finds_by_repository_name() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    await indexed(unit_of_work, repository)
    server = build_server(runtime_over(unit_of_work, search=FakeChunkSearch([chunk()])))

    answer = await call(server, "search_code", repository="ducktective", query="отчёт")

    assert "app/report.py:1-5" in answer


async def test_unknown_repository_is_answered_with_available_names() -> None:
    """Неверно названный репозиторий — повод показать выбор, а не вернуть ошибку протокола."""
    unit_of_work = FakeUnitOfWork()
    registered(unit_of_work)
    server = build_server(runtime_over(unit_of_work))

    answer = await call(server, "search_code", repository="duck", query="отчёт")

    assert "не найден" in answer
    assert "ducktective" in answer


async def test_empty_answer_names_the_missing_index() -> None:
    """Пустая выдача по несобранному индексу неотличима от честного «нет такого»."""
    unit_of_work = FakeUnitOfWork()
    registered(unit_of_work)
    server = build_server(runtime_over(unit_of_work))

    answer = await call(server, "search_code", repository="ducktective", query="отчёт")

    assert "ничего не нашлось" in answer
    assert "индекс не собран" in answer


async def test_empty_answer_over_ready_index_says_nothing_found() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    await indexed(unit_of_work, repository)
    server = build_server(runtime_over(unit_of_work))

    answer = await call(server, "search_code", repository="ducktective", query="отчёт")

    assert "ничего не нашлось" in answer
    assert "не собран" not in answer


async def test_answer_is_signed_with_the_indexed_revision() -> None:
    """Без ревизии нельзя судить, насколько ответ свеж."""
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    await indexed(unit_of_work, repository)
    server = build_server(runtime_over(unit_of_work, search=FakeChunkSearch([chunk()])))

    answer = await call(server, "search_code", repository="ducktective", query="отчёт")

    assert f"— ducktective: индекс на ревизии {'a' * 8}, собран " in answer


async def test_oversized_fragment_is_clipped() -> None:
    """Один чанк на весь файл не имеет права занять всё окно вызывающей модели."""
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    await indexed(unit_of_work, repository)
    giant = FakeChunkSearch([chunk(content="строка кода\n" * 40000)])
    server = build_server(runtime_over(unit_of_work, search=giant))

    answer = await call(server, "search_code", repository="ducktective", query="отчёт")

    assert "обрезано, ещё" in answer
    assert len(answer) < MAX_ANSWER_CHARS + 500


async def test_repositories_are_listed_with_their_index_state() -> None:
    """Без списка имя репозитория приходится угадывать."""
    unit_of_work = FakeUnitOfWork()
    indexed_repository = registered(unit_of_work)
    await indexed(unit_of_work, indexed_repository)
    registered(unit_of_work, "sandbox")
    server = build_server(runtime_over(unit_of_work))

    answer = await call(server, "list_repositories")

    assert "ducktective — индекс на ревизии" in answer
    assert "sandbox — индекс не собран" in answer


async def test_definition_returns_body() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    await indexed(unit_of_work, repository)
    symbols = FakeSymbolReader(by_name={"build": [symbol("app.report.Builder.build")]})
    server = build_server(runtime_over(unit_of_work, symbols=symbols))

    answer = await call(server, "get_definition", repository="ducktective", name="build")

    assert "app.report.Builder.build" in answer
    assert "return 1" in answer


async def test_callers_are_listed_with_location() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    await indexed(unit_of_work, repository)
    symbols = FakeSymbolReader(
        by_name={"build": [symbol("app.report.Builder.build")]},
        callers=[symbol("app.api.handler", kind=SymbolKind.FUNCTION, path="app/api.py")],
    )
    server = build_server(runtime_over(unit_of_work, symbols=symbols))

    answer = await call(server, "find_callers", repository="ducktective", name="build")

    assert "app.api.handler" in answer
    assert "app/api.py:10-20" in answer


async def test_file_context_shows_both_directions() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    await indexed(unit_of_work, repository)
    symbols = FakeSymbolReader(
        covering=[symbol("app.report.Builder.build")],
        callees=[symbol("app.report.compute", kind=SymbolKind.FUNCTION)],
        callers=[symbol("app.api.handler", kind=SymbolKind.FUNCTION, path="app/api.py")],
    )
    server = build_server(runtime_over(unit_of_work, symbols=symbols))

    answer = await call(
        server,
        "get_file_context",
        repository="ducktective",
        path="app/report.py",
        start_line=10,
        end_line=20,
    )

    assert "Вызывает" in answer
    assert "Вызывается из" in answer
    assert "app.report.compute" in answer
    assert "app.api.handler" in answer
