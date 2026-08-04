"""Хранение хода прогона между запусками.

Состояние графа переживает падение воркера, поэтому прерванное расследование
дочитывает оставшиеся файлы вместо того, чтобы читать все заново. При
локальной модели в 19 токенов в секунду это разница между минутами и часами.
"""

from collections.abc import (
    AsyncIterator,
)
from contextlib import (
    asynccontextmanager,
)
from typing import (
    TYPE_CHECKING,
    Any,
)

from langgraph.checkpoint.postgres.aio import (
    AsyncPostgresSaver,
)
from langgraph.checkpoint.serde.jsonplus import (
    JsonPlusSerializer,
)
from psycopg.rows import (
    dict_row,
)
from psycopg_pool import (
    AsyncConnectionPool,
)

from ducktective.core.diff.value_objects import (
    ChangeType,
    DiffSide,
)
from ducktective.core.llm.value_objects import (
    LlmUsage,
    ModelRequirements,
)
from ducktective.core.retrieval.context import (
    ContextOrigin,
    ContextPiece,
    DiffContext,
)
from ducktective.core.review.degradation import (
    DegradationKind,
    NodeDegradation,
    ReviewStage,
)
from ducktective.core.review.drafts import (
    EvidenceDraft,
    FindingDraft,
)
from ducktective.core.review.entities import (
    Evidence,
    Finding,
    ReviewFile,
    ReviewHunk,
)
from ducktective.core.review.pipeline import (
    PipelineRequest,
)
from ducktective.core.review.value_objects import (
    EvidenceKind,
    FindingCategory,
    FindingProducer,
    FindingStatus,
    Severity,
)
from ducktective.review_graph.state import (
    FileDrafts,
    FileReviewTask,
    MergedDraft,
    ReviewGraphState,
)


if TYPE_CHECKING:
    from psycopg import (
        AsyncConnection,
    )


CHECKPOINTED_TYPES: tuple[type, ...] = (
    ReviewGraphState,
    FileReviewTask,
    FileDrafts,
    MergedDraft,
    PipelineRequest,
    ModelRequirements,
    LlmUsage,
    ReviewFile,
    ReviewHunk,
    ChangeType,
    DiffSide,
    DiffContext,
    ContextPiece,
    ContextOrigin,
    FindingDraft,
    EvidenceDraft,
    Finding,
    Evidence,
    EvidenceKind,
    FindingCategory,
    FindingProducer,
    FindingStatus,
    Severity,
    NodeDegradation,
    DegradationKind,
    ReviewStage,
)
"""Всё, что граф кладёт в состояние.

Перечень явный, потому что LangGraph восстанавливает из чекпоинта только
разрешённые типы, а незнакомый молча теряет. Тип, забытый здесь, ломает
возобновление ровно в тот момент, когда оно нужно, — поэтому перечень
проверяется тестом, а не глазами.
"""


def build_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINTED_TYPES)


@asynccontextmanager
async def open_checkpointer(
    database_url: str,
    *,
    pool_size: int = 4,
) -> AsyncIterator[AsyncPostgresSaver]:
    """Открывает хранилище чекпоинтов на своём пуле соединений.

    Пул отдельный от SQLAlchemy: чекпоинтер работает на psycopg, а прогон
    держит его открытым минутами — общий пул он бы просто занял.

    Схему создаёт сам чекпоинтер: таблицы `checkpoint*` принадлежат LangGraph,
    и вести их миграциями значит повторять чужую версионность у себя.
    """
    pool: AsyncConnectionPool[AsyncConnection[dict[str, Any]]] = AsyncConnectionPool(
        conninfo=to_psycopg_url(database_url),
        max_size=pool_size,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open(wait=True)
    try:
        checkpointer = AsyncPostgresSaver(pool, serde=build_serializer())
        await checkpointer.setup()
        yield checkpointer
    finally:
        await pool.close()


def to_psycopg_url(database_url: str) -> str:
    """Тот же адрес базы без драйвера SQLAlchemy в схеме.

    В настройках он записан как `postgresql+asyncpg://`, а psycopg понимает
    только `postgresql://` — заводить вторую настройку под ту же базу значит
    однажды развести их по разным хостам.
    """
    scheme, separator, rest = database_url.partition("://")
    if not separator:
        return database_url
    return f"{scheme.partition('+')[0]}://{rest}"
