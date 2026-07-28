from uuid import (
    uuid4,
)

from sqlalchemy import (
    insert,
    literal,
    select,
)
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from ducktective.core.types import (
    CodeChunkId,
    ContentHash,
    EmbeddingModelId,
    RepositoryId,
)
from ducktective.storage.models.indexing import (
    ChunkEmbeddingModel,
    CodeChunkModel,
    EmbeddingModelModel,
    SourceFileModel,
)


class SqlAlchemyEmbeddingStore:
    """Векторы чанков в pgvector."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register_model(self, name: str, dimensions: int) -> EmbeddingModelId:
        existing = (
            await self._session.execute(
                select(EmbeddingModelModel.id).where(EmbeddingModelModel.name == name)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return EmbeddingModelId(existing)

        model_id = EmbeddingModelId(uuid4())
        await self._session.execute(
            insert(EmbeddingModelModel).values(
                id=model_id,
                name=name,
                dimensions=dimensions,
                is_active=True,
            )
        )
        return model_id

    async def missing_chunks(
        self,
        repository_id: RepositoryId,
        model_id: EmbeddingModelId,
    ) -> list[tuple[CodeChunkId, ContentHash, str]]:
        embedded = select(ChunkEmbeddingModel.chunk_id).where(
            ChunkEmbeddingModel.chunk_id == CodeChunkModel.id,
            ChunkEmbeddingModel.embedding_model_id == model_id,
        )
        statement = (
            select(CodeChunkModel.id, CodeChunkModel.content_hash, CodeChunkModel.content)
            .join(SourceFileModel, SourceFileModel.id == CodeChunkModel.file_id)
            .where(
                CodeChunkModel.repository_id == repository_id,
                SourceFileModel.is_deleted.is_(False),
                ~embedded.exists(),
            )
        )

        rows = await self._session.execute(statement)
        return [
            (CodeChunkId(row.id), ContentHash(row.content_hash), row.content) for row in rows.all()
        ]

    async def reuse_by_hash(
        self,
        repository_id: RepositoryId,
        model_id: EmbeddingModelId,
    ) -> int:
        """Переносит готовые векторы на чанки с тем же содержимым.

        Отбирается один вектор на хеш: содержимое совпадает, значит и вектор
        для них один и тот же, а какой из дублей послужил источником — неважно.
        """
        source = (
            select(
                CodeChunkModel.content_hash.label("content_hash"),
                ChunkEmbeddingModel.embedding.label("embedding"),
            )
            .join(ChunkEmbeddingModel, ChunkEmbeddingModel.chunk_id == CodeChunkModel.id)
            .where(
                CodeChunkModel.repository_id == repository_id,
                ChunkEmbeddingModel.embedding_model_id == model_id,
            )
            .distinct(CodeChunkModel.content_hash)
            .subquery()
        )
        embedded = select(ChunkEmbeddingModel.chunk_id).where(
            ChunkEmbeddingModel.chunk_id == CodeChunkModel.id,
            ChunkEmbeddingModel.embedding_model_id == model_id,
        )
        candidates = (
            select(
                CodeChunkModel.id.label("chunk_id"),
                literal(model_id).label("embedding_model_id"),
                source.c.embedding.label("embedding"),
            )
            .join(source, source.c.content_hash == CodeChunkModel.content_hash)
            .where(
                CodeChunkModel.repository_id == repository_id,
                ~embedded.exists(),
            )
        )

        result = await self._session.execute(
            postgres_insert(ChunkEmbeddingModel)
            .from_select(["chunk_id", "embedding_model_id", "embedding"], candidates)
            .on_conflict_do_nothing()
            .returning(ChunkEmbeddingModel.chunk_id)
        )
        return len(result.all())

    async def store(
        self,
        model_id: EmbeddingModelId,
        vectors: list[tuple[CodeChunkId, list[float]]],
    ) -> None:
        if not vectors:
            return

        await self._session.execute(
            postgres_insert(ChunkEmbeddingModel)
            .values(
                [
                    {
                        "chunk_id": chunk_id,
                        "embedding_model_id": model_id,
                        "embedding": vector,
                    }
                    for chunk_id, vector in vectors
                ]
            )
            .on_conflict_do_nothing()
        )
