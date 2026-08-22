from uuid import (
    uuid4,
)

from ducktective.core.retrieval.ports import (
    ChunkHit,
)
from ducktective.core.types import (
    CodeChunkId,
    RepositoryId,
)
from ducktective.retrieval.hybrid import (
    HybridSearch,
)


def hit(name: str, score: float = 1.0) -> ChunkHit:
    return ChunkHit(
        chunk_id=CodeChunkId(uuid4()),
        symbol_id=None,
        path=f"app/{name}.py",
        breadcrumb=f"app.{name}",
        content=f"def {name}(): ...",
        start_line=1,
        end_line=3,
        score=score,
    )


class FakeSource:
    def __init__(self, hits: list[ChunkHit]) -> None:
        self.hits = hits
        self.requested_limits: list[int] = []

    async def search_chunks(
        self,
        repository_id: RepositoryId,
        query: str,
        *,
        limit: int = 20,
    ) -> list[ChunkHit]:
        self.requested_limits.append(limit)
        return self.hits[:limit]


async def search(
    lexical: list[ChunkHit],
    vector: list[ChunkHit],
    *,
    limit: int = 10,
) -> list[ChunkHit]:
    hybrid = HybridSearch(FakeSource(lexical), FakeSource(vector))
    return await hybrid.search_chunks(RepositoryId(uuid4()), "запрос", limit=limit)


async def test_result_present_in_both_sources_wins() -> None:
    """Ради этого ранги и складываются: согласие двух источников — сильный сигнал."""
    shared = hit("shared")
    lexical = [hit("only_lexical"), shared]
    vector = [hit("only_vector"), shared]

    results = await search(lexical, vector)

    assert results[0].chunk_id == shared.chunk_id


async def test_incomparable_scores_do_not_leak_into_ranking() -> None:
    """У лексики и векторов разные шкалы — учитывается только порядок.

    Оценки источников не переносятся в итог ни в каком виде: место
    определяют ранг и вес источника, а собственная шкала остаётся снаружи.
    """
    lexical = [hit("first", score=0.001)]
    vector = [hit("second", score=999.0)]

    swapped_lexical = [hit("first", score=999.0)]
    swapped_vector = [hit("second", score=0.001)]

    results = await search(lexical, vector)
    swapped = await search(swapped_lexical, swapped_vector)

    assert [result.breadcrumb for result in results] == [result.breadcrumb for result in swapped]
    assert all(result.score < 1.0 for result in results)


async def test_results_of_one_source_survive_when_other_is_empty() -> None:
    lexical = [hit("alpha"), hit("beta")]

    results = await search(lexical, [])

    assert [result.breadcrumb for result in results] == ["app.alpha", "app.beta"]


async def test_nothing_found_anywhere_gives_nothing() -> None:
    assert await search([], []) == []


async def test_limit_is_respected() -> None:
    lexical = [hit(f"item_{number}") for number in range(20)]

    results = await search(lexical, [], limit=5)

    assert len(results) == 5


async def test_sources_are_asked_wider_than_the_answer() -> None:
    """Слияние имеет смысл, только когда есть из чего выбирать."""
    lexical_source = FakeSource([hit("alpha")])
    vector_source = FakeSource([hit("beta")])

    await HybridSearch(lexical_source, vector_source).search_chunks(
        RepositoryId(uuid4()),
        "запрос",
        limit=5,
        candidates=40,
    )

    assert lexical_source.requested_limits == [40]
    assert vector_source.requested_limits == [40]


async def test_original_location_survives_merging() -> None:
    shared = hit("shared")

    results = await search([shared], [shared])

    assert results[0].path == shared.path
    assert results[0].start_line == shared.start_line
    assert results[0].content == shared.content
