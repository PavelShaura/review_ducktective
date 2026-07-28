from sqlalchemy import (
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from ducktective.core.indexing.ports import (
    Embedder,
)
from ducktective.core.retrieval.ports import (
    ChunkHit,
)
from ducktective.core.types import (
    CodeChunkId,
    CodeSymbolId,
    RepositoryId,
)
from ducktective.storage.models.indexing import (
    ChunkEmbeddingModel,
    CodeChunkModel,
    EmbeddingModelModel,
    SourceFileModel,
)


class VectorSearch:
    """Поиск по смыслу через pgvector.

    Дополняет лексический, а не заменяет его: находит места, описанные
    другими словами, но размывает точные имена — на них отвечает поиск
    по словам.
    """

    def __init__(self, session: AsyncSession, embedder: Embedder) -> None:
        self._session = session
        self._embedder = embedder

    async def search_chunks(
        self,
        repository_id: RepositoryId,
        query: str,
        *,
        limit: int = 20,
    ) -> list[ChunkHit]:
        model_id = await self._active_model_id()
        if model_id is None:
            return []

        vectors = await self._embedder.embed([query])
        if not vectors:
            return []

        distance = ChunkEmbeddingModel.embedding.cosine_distance(vectors[0])
        statement = (
            select(
                CodeChunkModel.id,
                CodeChunkModel.symbol_id,
                SourceFileModel.path,
                CodeChunkModel.breadcrumb,
                CodeChunkModel.content,
                CodeChunkModel.start_line,
                CodeChunkModel.end_line,
                distance.label("distance"),
            )
            .join(ChunkEmbeddingModel, ChunkEmbeddingModel.chunk_id == CodeChunkModel.id)
            .join(SourceFileModel, SourceFileModel.id == CodeChunkModel.file_id)
            .where(
                CodeChunkModel.repository_id == repository_id,
                ChunkEmbeddingModel.embedding_model_id == model_id,
                SourceFileModel.is_deleted.is_(False),
            )
            .order_by(distance)
            .limit(limit)
        )

        rows = await self._session.execute(statement)
        return [
            ChunkHit(
                chunk_id=CodeChunkId(row.id),
                symbol_id=CodeSymbolId(row.symbol_id) if row.symbol_id else None,
                path=row.path,
                breadcrumb=row.breadcrumb,
                content=row.content,
                start_line=row.start_line,
                end_line=row.end_line,
                score=1.0 - float(row.distance),
            )
            for row in rows
        ]

    async def _active_model_id(self) -> object | None:
        """Модель, которой считались векторы этого индекса.

        Их может быть несколько — при сравнении моделей старый набор
        остаётся рядом с новым, — поэтому выбор явный, а не «любая».
        """
        statement = select(EmbeddingModelModel.id).where(
            EmbeddingModelModel.name == self._embedder.name
        )
        return (await self._session.execute(statement)).scalar_one_or_none()
