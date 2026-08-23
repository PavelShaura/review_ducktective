from uuid import (
    uuid4,
)

from ducktective.core.retrieval.navigation import (
    DOC_LANGUAGES,
)
from ducktective.core.retrieval.ports import (
    ChunkHit,
    RepositoryDigest,
)
from ducktective.core.types import (
    CodeChunkId,
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


def chunk(path: str) -> ChunkHit:
    return ChunkHit(
        chunk_id=CodeChunkId(uuid4()),
        symbol_id=None,
        path=path,
        breadcrumb=path,
        content="Решение: транзакция открывается в use case",
        start_line=1,
        end_line=3,
        score=1.0,
    )


def build_navigator(
    reader: FakeSymbolReader | None = None,
    search: FakeChunkSearch | None = None,
) -> IndexedCodeNavigator:
    return IndexedCodeNavigator(
        REPOSITORY_ID,
        symbols=reader or FakeSymbolReader(),
        search=search or FakeChunkSearch(),
    )


async def test_summary_says_what_the_project_is_made_of() -> None:
    """Первый ход разговора: на чём написано, где что лежит, велик ли."""
    reader = FakeSymbolReader(
        digest=RepositoryDigest(
            files=8116,
            symbols=45546,
            languages=(("python", 7000), ("javascript", 521)),
            directories=(("src", 6000), ("static", 2000)),
        )
    )

    answer = await build_navigator(reader).describe_repository()

    assert answer.note is not None
    assert "8116" in answer.note
    assert "javascript — 521" in answer.note
    assert "static" in answer.note


async def test_an_empty_index_is_named_as_empty() -> None:
    answer = await build_navigator().describe_repository()

    assert answer.note is not None
    assert "пуст" in answer.note


async def test_documentation_is_searched_apart_from_code() -> None:
    """«Как принято» и «как сделано» — разные вопросы к разным файлам."""
    search = FakeChunkSearch([chunk("docs/06-decisions.md")])

    answer = await build_navigator(search=search).project_docs("транзакции")

    assert [fragment.path for fragment in answer.fragments] == ["docs/06-decisions.md"]
    assert search.languages == [DOC_LANGUAGES]


async def test_documentation_answer_admits_it_may_lag_behind_the_code() -> None:
    search = FakeChunkSearch([chunk("README.md")])

    answer = await build_navigator(search=search).project_docs("транзакции")

    assert answer.note is not None
    assert "search_code" in answer.note


async def test_nothing_in_the_documentation_is_said_plainly() -> None:
    answer = await build_navigator().project_docs("чего тут нет")

    assert answer.is_empty
    assert answer.note is not None
