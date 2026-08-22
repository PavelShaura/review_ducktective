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
    _is_code_like,
    _query_stages,
    _terms_of,
    looks_literal,
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
    terms = _terms_of("declaration pack", split_identifiers=True)

    assert terms == {"declaration", "pack"}


def test_long_query_is_cut_to_a_workable_size() -> None:
    """Условие из сотен слов через «или» подходит подо всю базу.

    Ранг тогда считается для каждого фрагмента, `LIMIT` от этого не спасает,
    и запрос идёт минутами — на закрытой базе восемь, держа прогон целиком.
    """
    query = " ".join(f"identifier_number_{index}" for index in range(500))

    terms = _terms_of(query, split_identifiers=True)

    assert len(terms) == MAX_QUERY_TERMS


def test_short_words_lose_to_long_ones_when_the_query_is_cut() -> None:
    """`if` и `id` есть везде и выдачу не сужают."""
    long_names = [f"declarationhandler{index}" for index in range(MAX_QUERY_TERMS * 2)]
    query = " ".join([*long_names, "if", "to", "id", "or"])

    terms = _terms_of(query, split_identifiers=True)

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
    terms = _terms_of(review_file(LICENSE_NOTICE).added_code, split_identifiers=True)

    assert len(terms) <= MAX_QUERY_TERMS


@pytest.mark.parametrize("patch_text", ["", "     only_context()\n", "-    only_removed()\n"])
async def test_nothing_added_means_nothing_to_search_for(patch_text: str) -> None:
    search = FakeChunkSearch()

    await DiffContextBuilder(FakeSymbolReader(), search).build(
        REPOSITORY_ID,
        review_file(patch_text),
    )

    assert search.queries == []


def test_literal_is_searched_before_its_parts() -> None:
    """`/catalog_branch_select` лежит в индексе целиком, вместе со слешем.

    Разобранный на части, он превращается в `catalog | unit | select` —
    три самых частых слова кодовой базы, и единственное точное совпадение
    тонет под десятками вхождений слова `unit`.
    """
    written = _terms_of("/catalog_branch_select", split_identifiers=False)
    parts = _terms_of("/catalog_branch_select", split_identifiers=True)

    assert written == {"/catalog_branch_select"}
    assert {"catalog", "branch", "select"} <= parts

    exact, split = _query_stages("/catalog_branch_select")
    assert (len(exact), len(split)) == (1, 1)


def test_prose_around_a_literal_does_not_come_first() -> None:
    """Слова вопроса встречаются повсюду; литерал — в одном месте."""
    written = _terms_of("как используется url = '/catalog_branch_select'", split_identifiers=False)

    code_like = {term for term in written if _is_code_like(term)}

    assert code_like == {"/catalog_branch_select"}
    assert "используется" in written


def test_plain_question_has_no_literal_stage() -> None:
    """Вопросу без кода искать нечего, кроме собственных слов."""
    exact, split = _query_stages("где проверяются права доступа?")

    assert (len(exact), len(split)) == (1, 0)


@pytest.mark.parametrize(
    "term",
    ["/catalog_branch_select", "review_run", "ReviewRun", "app.module", "report2"],
)
def test_code_like_terms_are_recognised(term: str) -> None:
    assert _is_code_like(term)


@pytest.mark.parametrize("term", ["права", "url", "используется", "framework"])
def test_plain_words_are_not_code_like(term: str) -> None:
    assert not _is_code_like(term)


def test_literal_question_trusts_words_over_vectors() -> None:
    """У точного совпадения вектор предлагает похожее вместо того самого."""
    assert looks_literal("/catalog_branch_select")
    assert looks_literal("что делает AccessChecker.has_section_permission?")


def test_plain_question_trusts_vectors_over_words() -> None:
    """Код английский, вопрос русский — лексике совпадать не с чем."""
    assert not looks_literal("где проверяются права доступа к паку?")
    assert not looks_literal("зачем нужен этот модуль")


def test_pasted_signature_keeps_the_name_whole() -> None:
    """В чат вставляют код, и пробелы делят его не там, где надо.

    `def get_branch_for_reader(profile: ReaderProfile)` разбивался в слово
    `get_branch_for_reader(profile` — со скобкой и параметром внутри, — и точная
    ступень промахивалась на самом прямом из запросов.
    """
    terms = _terms_of(
        "def get_branch_for_reader(profile: ReaderProfile) -> Optional[Unit]:",
        split_identifiers=False,
    )

    assert "get_branch_for_reader" in terms
    assert "ReaderProfile" in terms


def test_rare_name_is_searched_alone_before_the_common_ones() -> None:
    """`Unit` и `Optional` есть в каждом втором файле и топят редкое имя."""
    exact, _ = _query_stages("def get_branch_for_reader(profile: ReaderProfile) -> Optional[Unit]:")

    assert len(exact) >= 2
