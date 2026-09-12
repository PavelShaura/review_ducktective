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
from ducktective.application.indexing.embedders import (
    EmbedderCatalogue,
    EmbedderChoice,
)
from ducktective.application.retrieval.read_index import (
    NavigateCode,
    SurveyRepositories,
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
from ducktective.core.retrieval.navigation import (
    NavigationSource,
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
from ducktective.retrieval.navigation import (
    IndexedNavigators,
)
from tests.fakes import (
    FakeChunkSearch,
    FakeSymbolReader,
    FakeUnitOfWork,
)


def catalogue(*names: str) -> EmbedderCatalogue:
    return EmbedderCatalogue(
        [
            EmbedderChoice(key=name, title=name, vector_set=name)
            for name in names or ("fake-embedder",)
        ]
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


def navigation(
    unit_of_work: FakeUnitOfWork,
    *,
    reader: FakeSymbolReader | None = None,
    search: FakeChunkSearch | None = None,
) -> NavigateCode:
    return NavigateCode(
        unit_of_work,
        IndexedNavigators(
            symbols=reader or FakeSymbolReader(),
            search=search or FakeChunkSearch(),
        ),
    )


async def test_search_returns_matches_with_location() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    search = FakeChunkSearch([chunk()])

    answer = await navigation(unit_of_work, search=search).search_code(
        TENANT_ID,
        repository.id,
        "отчёт",
    )

    assert search.queries == ["отчёт"]
    assert [fragment.location for fragment in answer.fragments] == ["app/report.py:1-5"]
    assert answer.source is NavigationSource.INDEX


async def test_search_of_foreign_repository_is_denied() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work, tenant_id=OTHER_TENANT_ID)
    search = FakeChunkSearch([chunk()])

    with pytest.raises(PermissionDeniedError):
        await navigation(unit_of_work, search=search).search_code(
            TENANT_ID,
            repository.id,
            "отчёт",
        )

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

    answer = await navigation(unit_of_work, reader=reader).get_definition(
        TENANT_ID,
        repository.id,
        "build",
    )

    assert [fragment.path for fragment in answer.fragments] == [
        "app/report.py",
        "app/billing.py",
    ]
    assert all(fragment.text for fragment in answer.fragments)
    assert answer.note is not None


async def test_callers_are_looked_up_by_resolved_symbols() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    target = symbol("app.report.Builder.build")
    reader = FakeSymbolReader(
        by_name={"app.report.Builder.build": [target]},
        callers=[symbol("app.api.handler", kind=SymbolKind.FUNCTION, path="app/api.py")],
    )

    answer = await navigation(unit_of_work, reader=reader).find_callers(
        TENANT_ID,
        repository.id,
        "app.report.Builder.build",
    )

    assert reader.asked_caller_ids == [[target.symbol_id]]
    assert [fragment.title for fragment in answer.fragments] == ["app.api.handler · function"]


async def test_callers_of_unknown_symbol_do_not_reach_the_graph() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    reader = FakeSymbolReader()

    answer = await navigation(unit_of_work, reader=reader).find_callers(
        TENANT_ID,
        repository.id,
        "нет.такого",
    )

    assert answer.is_empty
    assert reader.asked_caller_ids == []


async def test_callers_come_without_body() -> None:
    """От вызывающего нужен контракт: телом крупный класс вытеснил бы остальных."""
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    reader = FakeSymbolReader(
        by_name={"build": [symbol("app.report.Builder.build")]},
        callers=[symbol("app.api.handler", text="def handler():\n    ...")],
    )

    answer = await navigation(unit_of_work, reader=reader).find_callers(
        TENANT_ID,
        repository.id,
        "build",
    )

    assert [fragment.text for fragment in answer.fragments] == ["def handler(self)"]


async def test_file_context_collects_symbols_and_both_directions() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    reader = FakeSymbolReader(
        covering=[symbol("app.report.Builder.build")],
        callees=[symbol("app.report.compute", kind=SymbolKind.FUNCTION)],
        callers=[symbol("app.api.handler", kind=SymbolKind.FUNCTION, path="app/api.py")],
    )

    answer = await navigation(unit_of_work, reader=reader).get_file_context(
        TENANT_ID,
        repository.id,
        "app/report.py",
        start_line=10,
        end_line=20,
    )

    assert reader.asked_lines == [(10, 20)]
    assert [fragment.title for fragment in answer.fragments] == [
        "app.report.Builder.build · method",
        "app.report.compute · function",
        "app.api.handler · function",
    ]


async def test_file_context_without_symbols_does_not_walk_the_graph() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    reader = FakeSymbolReader(callees=[symbol("app.report.compute")])

    answer = await navigation(unit_of_work, reader=reader).get_file_context(
        TENANT_ID,
        repository.id,
        "app/unknown.py",
        start_line=1,
        end_line=5,
    )

    assert answer.is_empty
    assert answer.note is not None


async def test_survey_lists_repositories_with_index_state() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)

    overviews = await SurveyRepositories(unit_of_work, embedders=catalogue()).execute(TENANT_ID)

    assert [overview.name for overview in overviews] == ["ducktective"]
    assert overviews[0].repository_id == repository.id
    assert not overviews[0].index.is_ready


async def test_survey_does_not_show_foreign_repositories() -> None:
    unit_of_work = FakeUnitOfWork()
    registered(unit_of_work, tenant_id=OTHER_TENANT_ID)

    assert await SurveyRepositories(unit_of_work, embedders=catalogue()).execute(TENANT_ID) == []
