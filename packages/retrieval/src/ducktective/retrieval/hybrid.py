from ducktective.core.retrieval.ports import (
    ChunkHit,
    ChunkSearch,
)
from ducktective.core.types import (
    RepositoryId,
)


RRF_CONSTANT = 60
"""Сглаживающая постоянная в формуле обратного ранга.

Значение из исходной работы про Reciprocal Rank Fusion: оно не даёт первому
месту в одном источнике перевесить весь другой список.
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
        limit: int = 10,
        candidates: int = 50,
    ) -> list[ChunkHit]:
        lexical_hits = await self._lexical.search_chunks(repository_id, query, limit=candidates)
        vector_hits = await self._vector.search_chunks(repository_id, query, limit=candidates)

        scores: dict[str, float] = {}
        by_id: dict[str, ChunkHit] = {}

        for hits in (lexical_hits, vector_hits):
            for rank, hit in enumerate(hits, start=1):
                key = str(hit.chunk_id)
                scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_CONSTANT + rank)
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
