from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.retrieval.read_index import (
    FindSymbolCallers,
    GetFileContext,
    GetSymbolDefinition,
    SearchCode,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import (
    VcsProvider,
)
from ducktective.core.indexing.value_objects import (
    SymbolKind,
)
from ducktective.core.retrieval.ports import (
    ChunkHit,
    SymbolContext,
)
from ducktective.core.types import (
    CodeChunkId,
    CodeSymbolId,
    QualifiedName,
    TenantId,
)
from tests.fakes import (
    FakeChunkSearch,
    FakeSymbolReader,
    FakeUnitOfWork,
)


TENANT_ID = TenantId(uuid4())
OTHER_TENANT_ID = TenantId(uuid4())


def symbol(
    name: str,
    *,
    kind: SymbolKind = SymbolKind.METHOD,
    path: str = "app/report.py",
    text: str = "def build(self):\n    return 1",
) -> SymbolContext:
    return SymbolContext(
        symbol_id=CodeSymbolId(uuid4()),
        qualified_name=QualifiedName(name),
        kind=kind,
        path=path,
        start_line=10,
        end_line=20,
        signature=f"def {name.rsplit('.', maxsplit=1)[-1]}(self)",
        docstring=None,
        text=text,
    )


def chunk(path: str = "app/report.py", content: str = "value = 1") -> ChunkHit:
    return ChunkHit(
        chunk_id=CodeChunkId(uuid4()),
        symbol_id=None,
        path=path,
        breadcrumb=f"{path} · Builder",
        content=content,
        start_line=1,
        end_line=5,
        score=0.9,
    )


def registered(unit_of_work: FakeUnitOfWork, *, tenant_id: TenantId = TENANT_ID) -> CodeRepository:
    repository = CodeRepository.register(
        tenant_id=tenant_id,
        name="ducktective",
        vcs_provider=VcsProvider.LOCAL,
        local_path=Path("/repos/ducktective"),
    )
    unit_of_work.code_repositories.add(repository)
    return repository


async def test_search_returns_matches_with_location() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    search = FakeChunkSearch([chunk()])

    matches = await SearchCode(unit_of_work, search).execute(TENANT_ID, repository.id, "отчёт")

    assert search.queries == ["отчёт"]
    assert [match.location for match in matches] == ["app/report.py:1-5"]


async def test_search_of_foreign_repository_is_denied() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work, tenant_id=OTHER_TENANT_ID)
    search = FakeChunkSearch([chunk()])

    with pytest.raises(PermissionDeniedError):
        await SearchCode(unit_of_work, search).execute(TENANT_ID, repository.id, "отчёт")

    assert search.queries == []


async def test_definition_returns_every_namesake() -> None:
    """Одноимённые символы возвращаются все: выбирать за спрашивающего нечем."""
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    reader = FakeSymbolReader(
        by_name={
            "build": [
                symbol("app.report.Builder.build"),
                symbol("app.billing.Invoice.build", path="app/billing.py"),
            ]
        }
    )

    found = await GetSymbolDefinition(unit_of_work, reader).execute(
        TENANT_ID,
        repository.id,
        "build",
    )

    assert [item.qualified_name for item in found] == [
        "app.report.Builder.build",
        "app.billing.Invoice.build",
    ]
    assert all(item.text for item in found)


async def test_callers_are_looked_up_by_resolved_symbols() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    target = symbol("app.report.Builder.build")
    reader = FakeSymbolReader(
        by_name={"app.report.Builder.build": [target]},
        callers=[symbol("app.api.handler", kind=SymbolKind.FUNCTION, path="app/api.py")],
    )

    callers = await FindSymbolCallers(unit_of_work, reader).execute(
        TENANT_ID,
        repository.id,
        "app.report.Builder.build",
    )

    assert reader.asked_caller_ids == [[target.symbol_id]]
    assert [caller.qualified_name for caller in callers] == ["app.api.handler"]


async def test_callers_of_unknown_symbol_do_not_reach_the_graph() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    reader = FakeSymbolReader()

    callers = await FindSymbolCallers(unit_of_work, reader).execute(
        TENANT_ID,
        repository.id,
        "нет.такого",
    )

    assert callers == []
    assert reader.asked_caller_ids == []


async def test_callers_come_without_body() -> None:
    """От вызывающего нужен контракт: телом крупный класс вытеснил бы остальных."""
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    reader = FakeSymbolReader(
        by_name={"build": [symbol("app.report.Builder.build")]},
        callers=[symbol("app.api.handler", text="def handler():\n    ...")],
    )

    callers = await FindSymbolCallers(unit_of_work, reader).execute(
        TENANT_ID, repository.id, "build"
    )

    assert [caller.text for caller in callers] == [""]
    assert [caller.signature for caller in callers] == ["def handler(self)"]


async def test_file_context_collects_symbols_and_both_directions() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    reader = FakeSymbolReader(
        covering=[symbol("app.report.Builder.build")],
        callees=[symbol("app.report.compute", kind=SymbolKind.FUNCTION)],
        callers=[symbol("app.api.handler", kind=SymbolKind.FUNCTION, path="app/api.py")],
    )

    view = await GetFileContext(unit_of_work, reader).execute(
        TENANT_ID,
        repository.id,
        "app/report.py",
        start_line=10,
        end_line=20,
    )

    assert reader.asked_lines == [(10, 20)]
    assert [item.qualified_name for item in view.symbols] == ["app.report.Builder.build"]
    assert [item.qualified_name for item in view.callees] == ["app.report.compute"]
    assert [item.qualified_name for item in view.callers] == ["app.api.handler"]


async def test_file_context_without_symbols_does_not_walk_the_graph() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    reader = FakeSymbolReader(callees=[symbol("app.report.compute")])

    view = await GetFileContext(unit_of_work, reader).execute(
        TENANT_ID,
        repository.id,
        "app/unknown.py",
        start_line=1,
        end_line=5,
    )

    assert view.is_empty
    assert view.callees == ()
