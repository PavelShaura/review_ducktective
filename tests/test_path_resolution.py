from uuid import (
    uuid4,
)

from ducktective.core.indexing.value_objects import (
    SymbolKind,
)
from ducktective.core.retrieval.ports import (
    SymbolContext,
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
INDEXED_PATH = "src/app/catalog/web/selection_packs.py"
ABSOLUTE_PATH = f"/home/user/projects/library/{INDEXED_PATH}"


def symbol(path: str = INDEXED_PATH) -> SymbolContext:
    return SymbolContext(
        symbol_id=CodeSymbolId(uuid4()),
        qualified_name=QualifiedName("BranchSelectPack"),
        kind=SymbolKind.CLASS,
        path=path,
        start_line=131,
        end_line=144,
        signature="class BranchSelectPack(BasePack)",
        docstring="Пак для выбора филиала.",
        text="class BranchSelectPack(BasePack):\n    url = '/catalog_branch_select'",
    )


class PathAwareSymbolReader(FakeSymbolReader):
    """Читатель, отвечающий символами только по тому пути, что лежит в индексе."""

    async def symbols_covering(
        self,
        repository_id: RepositoryId,
        path: str,
        start_line: int,
        end_line: int,
    ) -> list[SymbolContext]:
        self.asked_lines.append((start_line, end_line))
        return [symbol()] if path == INDEXED_PATH else []


def build_navigator(paths: list[str]) -> IndexedCodeNavigator:
    return IndexedCodeNavigator(
        REPOSITORY_ID,
        symbols=PathAwareSymbolReader(paths=paths),
        search=FakeChunkSearch(),
    )


async def test_absolute_path_resolves_to_the_indexed_one() -> None:
    """Человек называет файл так, как видит его у себя — абсолютным путём."""
    navigator = build_navigator([INDEXED_PATH])

    answer = await navigator.get_file_context(ABSOLUTE_PATH, start_line=1, end_line=200)

    assert not answer.is_empty
    assert answer.note is not None
    assert INDEXED_PATH in answer.note


async def test_bare_file_name_resolves_too() -> None:
    navigator = build_navigator([INDEXED_PATH])

    answer = await navigator.get_file_context("selection_packs.py", start_line=1, end_line=200)

    assert not answer.is_empty


async def test_unknown_path_names_the_similar_ones() -> None:
    """Пустой ответ и «такого файла нет» читаются одинаково, а значат разное."""
    navigator = build_navigator(["src/app/reports/selection_packs.py"])

    answer = await navigator.get_file_context(
        "/elsewhere/selection_packs.py",
        start_line=1,
        end_line=200,
    )

    assert answer.is_empty
    assert answer.note is not None
    assert "src/app/reports/selection_packs.py" in answer.note


async def test_ambiguous_name_is_not_guessed() -> None:
    """Один и тот же файл лежит в трёх плагинах — подставлять наугад нельзя."""
    navigator = build_navigator(
        [
            "src/app/catalog/selection_packs.py",
            "src/app/orders/selection_packs.py",
        ]
    )

    answer = await navigator.get_file_context("selection_packs.py", start_line=1, end_line=200)

    assert answer.is_empty
    assert answer.note is not None
    assert "src/app/catalog/selection_packs.py" in answer.note
