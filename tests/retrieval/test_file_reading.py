from uuid import (
    uuid4,
)

from ducktective.core.indexing.value_objects import (
    SymbolKind,
)
from ducktective.core.retrieval.navigation import (
    FragmentRole,
)
from ducktective.core.retrieval.ports import (
    SymbolContext,
    SymbolHit,
)
from ducktective.core.types import (
    CodeSymbolId,
    QualifiedName,
    RepositoryId,
)
from ducktective.retrieval.navigation import (
    IndexedCodeNavigator,
)
from tests.fakes import (
    FakeChunkSearch,
    FakeSymbolReader,
)


REPOSITORY_ID = RepositoryId(uuid4())
SETTINGS = "config/settings.ini"


def symbol(name: str, *, start: int, end: int, signature: str) -> SymbolContext:
    return SymbolContext(
        symbol_id=CodeSymbolId(uuid4()),
        qualified_name=QualifiedName(name),
        kind=SymbolKind.METHOD,
        path="app/report.py",
        start_line=start,
        end_line=end,
        signature=signature,
        docstring=None,
        text="",
    )


def hit(name: str) -> SymbolHit:
    return SymbolHit(
        symbol_id=CodeSymbolId(uuid4()),
        qualified_name=QualifiedName(name),
        kind=SymbolKind.CLASS,
        path="app/access.py",
        start_line=12,
        end_line=48,
        signature=f"class {name.rsplit('.', maxsplit=1)[-1]}:",
        score=0.9,
    )


def build_navigator(reader: FakeSymbolReader) -> IndexedCodeNavigator:
    return IndexedCodeNavigator(REPOSITORY_ID, symbols=reader, search=FakeChunkSearch())


async def test_a_file_without_symbols_can_still_be_read() -> None:
    """Миграция, файл настроек и шаблон — там обход по графу отвечать нечем."""
    reader = FakeSymbolReader(
        paths=[SETTINGS],
        lines={SETTINGS: "[database]\nhost = localhost"},
    )

    answer = await build_navigator(reader).read_file(SETTINGS, start_line=1, end_line=2)

    assert not answer.is_empty
    assert "host = localhost" in answer.fragments[0].text
    assert answer.fragments[0].role is FragmentRole.SOURCE


async def test_missing_file_names_similar_paths() -> None:
    reader = FakeSymbolReader(paths=[SETTINGS])

    answer = await build_navigator(reader).read_file("settings.ini", start_line=1, end_line=5)

    assert answer.is_empty
    assert answer.note is not None


async def test_outline_lists_definitions_without_their_bodies() -> None:
    """На файле в тысячу строк тела вытеснят из окна всё остальное."""
    reader = FakeSymbolReader(
        paths=["app/report.py"],
        in_file=[
            symbol("app.report.ReportBuilder.build", start=10, end=40, signature="def build(self)"),
            symbol("app.report.ReportBuilder.total", start=42, end=50, signature="def total(self)"),
        ],
    )

    answer = await build_navigator(reader).get_file_outline("app/report.py")

    assert answer.is_empty
    assert answer.note is not None
    assert "10-40" in answer.note
    assert "def build(self)" in answer.note
    assert "get_definition" in answer.note


async def test_outline_of_a_file_without_symbols_points_at_reading_it() -> None:
    reader = FakeSymbolReader(paths=[SETTINGS])

    answer = await build_navigator(reader).get_file_outline(SETTINGS)

    assert answer.note is not None
    assert "read_file" in answer.note


async def test_symbols_are_searched_by_name() -> None:
    """Спрашивающий помнит слово из имени, но не файл и не полное имя."""
    reader = FakeSymbolReader(by_query=[hit("app.access.AccessChecker")])

    answer = await build_navigator(reader).find_symbol("access")

    assert [fragment.role for fragment in answer.fragments] == [FragmentRole.NAME]
    assert answer.fragments[0].path == "app/access.py"
    assert answer.note is not None
    assert "get_definition" in answer.note


async def test_nothing_similar_is_said_plainly() -> None:
    answer = await build_navigator(FakeSymbolReader()).find_symbol("нетакого")

    assert answer.is_empty
    assert answer.note is not None
