from dataclasses import (
    dataclass,
)

from ducktective.core.indexing.ports import (
    Embedder,
)
from ducktective.core.ports import (
    UnitOfWork,
)
from ducktective.core.types import (
    RepositoryId,
)


DEFAULT_BATCH_SIZE = 64


@dataclass(frozen=True, kw_only=True)
class EmbeddingOutcome:
    model: str
    computed: int = 0
    reused: int = 0

    @property
    def total(self) -> int:
        return self.computed + self.reused


class BuildEmbeddings:
    """Досчитывает векторы для чанков, у которых их ещё нет.

    Вынесено из разбора кода намеренно: эмбеддинг — единственная часть
    индексации, которой нужна работающая модель, и её недоступность не должна
    оставлять репозиторий без символов и графа.

    Обращение к модели идёт вне транзакции: список чанков читается, векторы
    считаются, запись возвращается в базу короткими пачками. Прерванный
    прогон не теряет посчитанное — при следующем запуске досчитается остаток.
    """

    def __init__(
        self,
        unit_of_work: UnitOfWork,
        embedder: Embedder,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._embedder = embedder
        self._batch_size = batch_size

    async def execute(self, repository_id: RepositoryId) -> EmbeddingOutcome:
        async with self._unit_of_work:
            model_id = await self._unit_of_work.embeddings.register_model(
                self._embedder.name,
                self._embedder.dimensions,
            )
            reused = await self._unit_of_work.embeddings.reuse_by_hash(repository_id, model_id)
            pending = await self._unit_of_work.embeddings.missing_chunks(repository_id, model_id)
            await self._unit_of_work.commit()

        computed = 0
        for start in range(0, len(pending), self._batch_size):
            batch = pending[start : start + self._batch_size]
            vectors = await self._embedder.embed([content for _, _, content in batch])

            async with self._unit_of_work:
                await self._unit_of_work.embeddings.store(
                    model_id,
                    [
                        (chunk_id, vector)
                        for (chunk_id, _, _), vector in zip(batch, vectors, strict=True)
                    ],
                )
                await self._unit_of_work.commit()

            computed += len(batch)

        return EmbeddingOutcome(model=self._embedder.name, computed=computed, reused=reused)
