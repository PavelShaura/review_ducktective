from uuid import (
    uuid4,
)

from ducktective.core.diff.value_objects import (
    ChangeType,
)
from ducktective.core.indexing.value_objects import (
    SymbolKind,
)
from ducktective.core.retrieval.context import (
    ContextOrigin,
)
from ducktective.core.retrieval.ports import (
    ChunkHit,
    SymbolContext,
)
from ducktective.core.review.entities import (
    ReviewFile,
    ReviewHunk,
)
from ducktective.core.types import (
    CodeChunkId,
    CodeSymbolId,
    QualifiedName,
    RepositoryId,
    ReviewFileId,
    ReviewHunkId,
)
from ducktective.retrieval.diff_context import (
    DiffContextBuilder,
)
from tests.fakes import (
    FakeChunkSearch,
    FakeSymbolReader,
)


REPOSITORY_ID = RepositoryId(uuid4())


def symbol(
    name: str,
    *,
    kind: SymbolKind = SymbolKind.METHOD,
    text: str = "",
    path: str = "app/report.py",
    start_line: int = 10,
    end_line: int = 20,
) -> SymbolContext:
    return SymbolContext(
        symbol_id=CodeSymbolId(uuid4()),
        qualified_name=QualifiedName(name),
        kind=kind,
        path=path,
        start_line=start_line,
        end_line=end_line,
        signature=f"def {name.rsplit('.', maxsplit=1)[-1]}(self)",
        docstring=None,
        text=text or f"def {name.rsplit('.', maxsplit=1)[-1]}(self):\n    return 1",
    )


def chunk(path: str, content: str = "value = 1") -> ChunkHit:
    return ChunkHit(
        chunk_id=CodeChunkId(uuid4()),
        symbol_id=None,
        path=path,
        breadcrumb=path,
        content=content,
        start_line=1,
        end_line=5,
        score=1.0,
    )


def review_file(path: str = "app/report.py", new_start: int = 10, new_lines: int = 5) -> ReviewFile:
    return ReviewFile(
        id=ReviewFileId(uuid4()),
        path=path,
        previous_path=None,
        change_type=ChangeType.MODIFIED,
        language="python",
        added_lines=new_lines,
        removed_lines=0,
        hunks=[
            ReviewHunk(
                id=ReviewHunkId(uuid4()),
                old_start=new_start,
                old_lines=new_lines,
                new_start=new_start,
                new_lines=new_lines,
                header="@@",
                patch_text="+    return self.compute()\n",
            )
        ],
    )


async def test_changed_lines_resolve_to_symbols() -> None:
    reader = FakeSymbolReader(covering=[symbol("app.report.Builder.build")])

    context = await DiffContextBuilder(reader, FakeChunkSearch()).build(
        REPOSITORY_ID, review_file()
    )

    assert reader.asked_lines == [(10, 14)]
    assert [piece.qualified_name for piece in context.of_origin(ContextOrigin.CHANGED_SYMBOL)] == [
        "app.report.Builder.build"
    ]


async def test_module_symbol_is_not_taken_as_changed() -> None:
    """Модуль покрывает любую строку и вытеснил бы собой весь бюджет."""
    reader = FakeSymbolReader(
        covering=[
            symbol("app.report", kind=SymbolKind.MODULE, start_line=1, end_line=200),
            symbol("app.report.Builder.build"),
        ]
    )

    context = await DiffContextBuilder(reader, FakeChunkSearch()).build(
        REPOSITORY_ID, review_file()
    )

    assert [piece.qualified_name for piece in context.of_origin(ContextOrigin.CHANGED_SYMBOL)] == [
        "app.report.Builder.build"
    ]


async def test_callers_answer_what_breaks() -> None:
    reader = FakeSymbolReader(
        covering=[symbol("app.report.Builder.build")],
        callers=[symbol("app.api.handler", path="app/api.py")],
    )

    context = await DiffContextBuilder(reader, FakeChunkSearch()).build(
        REPOSITORY_ID, review_file()
    )

    assert [piece.qualified_name for piece in context.of_origin(ContextOrigin.CALLER)] == [
        "app.api.handler"
    ]


async def test_neighbours_are_reduced_to_their_contract() -> None:
    """От соседа нужен контракт, а не реализация: телом он вытеснит остальное."""
    reader = FakeSymbolReader(
        covering=[symbol("app.report.Builder.build")],
        callees=[
            symbol(
                "app.util.compute",
                text="def compute():\n    " + "x = 1\n    " * 100,
                path="app/util.py",
                start_line=5,
                end_line=105,
            )
        ],
    )

    context = await DiffContextBuilder(reader, FakeChunkSearch()).build(
        REPOSITORY_ID, review_file()
    )

    callee = context.of_origin(ContextOrigin.CALLEE)[0]
    assert "x = 1" not in callee.text
    assert "def compute" in callee.text


async def test_changed_symbol_is_taken_whole() -> None:
    body = "def build(self):\n    return self.compute()"
    reader = FakeSymbolReader(covering=[symbol("app.report.Builder.build", text=body)])

    context = await DiffContextBuilder(reader, FakeChunkSearch()).build(
        REPOSITORY_ID, review_file()
    )

    assert context.of_origin(ContextOrigin.CHANGED_SYMBOL)[0].text == body


async def test_similar_places_come_from_other_files() -> None:
    reader = FakeSymbolReader(covering=[symbol("app.report.Builder.build")])
    search = FakeChunkSearch([chunk("app/report.py"), chunk("app/billing.py")])

    context = await DiffContextBuilder(reader, search).build(REPOSITORY_ID, review_file())

    assert [piece.path for piece in context.of_origin(ContextOrigin.SIMILAR)] == ["app/billing.py"]


async def test_budget_stops_collection_and_is_reported() -> None:
    reader = FakeSymbolReader(
        covering=[
            symbol(
                f"app.report.Builder.method_{number}",
                start_line=10 + number * 10,
                end_line=18 + number * 10,
            )
            for number in range(50)
        ]
    )

    context = await DiffContextBuilder(reader, FakeChunkSearch(), token_budget=40).build(
        REPOSITORY_ID,
        review_file(),
    )

    assert context.token_count <= 40
    assert context.dropped > 0


async def test_structural_neighbours_outrank_search_results() -> None:
    """Обход графа точен по построению, поиск вероятностен."""
    reader = FakeSymbolReader(
        covering=[symbol("app.report.Builder.build")],
        callers=[symbol("app.api.handler", path="app/api.py")],
    )
    search = FakeChunkSearch([chunk("app/other.py")])

    context = await DiffContextBuilder(reader, search).build(REPOSITORY_ID, review_file())

    origins = [piece.origin for piece in context.pieces]
    assert origins.index(ContextOrigin.CALLER) < origins.index(ContextOrigin.SIMILAR)


async def test_file_without_known_symbols_yields_empty_context() -> None:
    context = await DiffContextBuilder(FakeSymbolReader(), FakeChunkSearch()).build(
        REPOSITORY_ID,
        review_file(),
    )

    assert context.is_empty
