from uuid import (
    uuid4,
)

import pytest

from ducktective.core.diff.value_objects import (
    ChangeType,
)
from ducktective.core.exceptions import (
    SearchTimedOutError,
)
from ducktective.core.retrieval.ports import (
    ChunkHit,
)
from ducktective.core.review.entities import (
    ReviewFile,
    ReviewHunk,
)
from ducktective.core.types import (
    RepositoryId,
    ReviewFileId,
    ReviewHunkId,
)
from ducktective.retrieval.diff_context import (
    DiffContextBuilder,
)
from ducktective.retrieval.lexical import (
    MAX_QUERY_TERMS,
    _distinctive_terms,
)
from tests.fakes import (
    FakeChunkSearch,
    FakeSymbolReader,
)


REPOSITORY_ID = RepositoryId(uuid4())

LICENSE_NOTICE = "\n".join(
    f"+ {word}" for word in ("copyright", "license", "software", "warranty", "permission") * 200
)


def test_short_query_reaches_the_database_whole() -> None:
    """У человека, спросившего два слова, отбирать нечего."""
    terms = _distinctive_terms("declaration pack")

    assert terms == {"declaration", "pack"}


def test_long_query_is_cut_to_a_workable_size() -> None:
    """Условие из сотен слов через «или» подходит подо всю базу.

    Ранг тогда считается для каждого фрагмента, `LIMIT` от этого не спасает,
    и запрос идёт минутами — на `ssuz` восемь, держа прогон целиком.
    """
    query = " ".join(f"identifier_number_{index}" for index in range(500))

    terms = _distinctive_terms(query)

    assert len(terms) == MAX_QUERY_TERMS


def test_short_words_lose_to_long_ones_when_the_query_is_cut() -> None:
    """`if` и `id` есть везде и выдачу не сужают."""
    long_names = [f"declarationhandler{index}" for index in range(MAX_QUERY_TERMS * 2)]
    query = " ".join([*long_names, "if", "to", "id", "or"])

    terms = _distinctive_terms(query)

    assert len(terms) == MAX_QUERY_TERMS
    assert not {"if", "to", "id", "or"} & terms


def review_file(patch_text: str) -> ReviewFile:
    return ReviewFile(
        id=ReviewFileId(uuid4()),
        path="THIRD_PARTY_NOTICES.txt",
        previous_path=None,
        change_type=ChangeType.MODIFIED,
        language=None,
        added_lines=1,
        removed_lines=1,
        hunks=[
            ReviewHunk(
                id=ReviewHunkId(uuid4()),
                old_start=1,
                old_lines=1,
                new_start=1,
                new_lines=1,
                header="@@",
                patch_text=patch_text,
            )
        ],
    )


def test_similar_places_are_searched_by_added_code_only() -> None:
    """Контекстные и удалённые строки описывают код, который не трогали."""
    file = review_file(
        "-    old_value = compute()\n+    new_value = recompute()\n     untouched()\n"
    )

    assert file.added_code == "    new_value = recompute()"


async def test_search_looks_for_what_was_added_not_for_the_whole_patch() -> None:
    search = FakeChunkSearch()
    file = review_file("-    was_here()\n+    became_this()\n     stayed()\n")

    await DiffContextBuilder(FakeSymbolReader(), search).build(REPOSITORY_ID, file)

    assert search.queries == ["    became_this()"]


class TimingOutSearch:
    """Поиск, который не уложился в отведённое время."""

    async def search_chunks(
        self,
        repository_id: RepositoryId,
        query: str,
        *,
        limit: int = 20,
    ) -> list[ChunkHit]:
        raise SearchTimedOutError("Поиск по индексу не уложился в 5000 мс")


async def test_timed_out_search_does_not_break_the_context() -> None:
    """Похожие места необязательны, а прогон, стоящий на запросе, — нет."""
    context = await DiffContextBuilder(FakeSymbolReader(), TimingOutSearch()).build(
        REPOSITORY_ID,
        review_file("+    became_this()\n"),
    )

    assert context.pieces == ()


def test_license_notice_no_longer_produces_a_query_of_hundreds_of_words() -> None:
    """Тот самый файл, на котором прогон встал на восемь минут."""
    terms = _distinctive_terms(review_file(LICENSE_NOTICE).added_code)

    assert len(terms) <= MAX_QUERY_TERMS


@pytest.mark.parametrize("patch_text", ["", "     only_context()\n", "-    only_removed()\n"])
async def test_nothing_added_means_nothing_to_search_for(patch_text: str) -> None:
    search = FakeChunkSearch()

    await DiffContextBuilder(FakeSymbolReader(), search).build(
        REPOSITORY_ID,
        review_file(patch_text),
    )

    assert search.queries == []
