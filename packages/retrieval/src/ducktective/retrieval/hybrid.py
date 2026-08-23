from ducktective.core.retrieval.ports import (
    ChunkHit,
    ChunkSearch,
)
from ducktective.core.types import (
    RepositoryId,
)
from ducktective.retrieval.lexical import (
    looks_literal,
)


RRF_CONSTANT = 60
"""Сглаживающая постоянная в формуле обратного ранга.

Значение из исходной работы про Reciprocal Rank Fusion: оно не даёт первому
месту в одном источнике перевесить весь другой список.
"""

LITERAL_WEIGHTS = (1.0, 0.6)
PROSE_WEIGHTS = (0.6, 1.0)
"""Чему верить больше — словам или векторам, в зависимости от запроса.

Спросили литералом — `/catalog_branch_select`, `AccessChecker` — отвечают
слова: совпадение точное и единственное, а вектор на таком запросе
предлагает похожее вместо того самого.

Спросили словами — «где проверяются права» — отвечают векторы. Код
английский, вопрос русский, и лексической половине совпадать не с чем:
на живом индексе закрытой базы она отдавала миграции и тесты, где случайно
встретились слова вопроса.

Перевес мягкий, не отключение: у обеих половин остаётся право поднять
фрагмент, который вторая не нашла, — ради этого слияние и делалось.
"""


class HybridSearch:
    """Слияние поиска по словам и по смыслу.

    Оценки двух источников несравнимы: ts_rank_cd и косинусная близость живут
    в разных шкалах, и складывать их напрямую бессмысленно. Складываются ранги:
    фрагмент, попавший в оба списка, поднимается выше того, кто был первым
    в одном и отсутствует в другом.
    """

    def __init__(self, lexical: ChunkSearch, vector: ChunkSearch) -> None:
        self._lexical = lexical
        self._vector = vector

    async def search_chunks(
        self,
        repository_id: RepositoryId,
        query: str,
        *,
        languages: tuple[str, ...] = (),
        limit: int = 10,
        candidates: int = 50,
    ) -> list[ChunkHit]:
        lexical_hits = await self._lexical.search_chunks(
            repository_id,
            query,
            languages=languages,
            limit=candidates,
        )
        vector_hits = await self._vector.search_chunks(
            repository_id,
            query,
            languages=languages,
            limit=candidates,
        )

        lexical_weight, vector_weight = LITERAL_WEIGHTS if looks_literal(query) else PROSE_WEIGHTS

        scores: dict[str, float] = {}
        by_id: dict[str, ChunkHit] = {}

        for hits, weight in ((lexical_hits, lexical_weight), (vector_hits, vector_weight)):
            for rank, hit in enumerate(hits, start=1):
                key = str(hit.chunk_id)
                scores[key] = scores.get(key, 0.0) + weight / (RRF_CONSTANT + rank)
                by_id.setdefault(key, hit)

        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        return [
            ChunkHit(
                chunk_id=by_id[key].chunk_id,
                symbol_id=by_id[key].symbol_id,
                path=by_id[key].path,
                breadcrumb=by_id[key].breadcrumb,
                content=by_id[key].content,
                start_line=by_id[key].start_line,
                end_line=by_id[key].end_line,
                score=score,
            )
            for key, score in ordered[:limit]
        ]
