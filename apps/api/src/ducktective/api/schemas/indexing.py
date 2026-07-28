from datetime import (
    datetime,
)
from uuid import (
    UUID,
)

from pydantic import (
    BaseModel,
)

from ducktective.application.indexing.views import (
    IndexStateView,
)
from ducktective.core.indexing.value_objects import (
    STAGE_TITLES,
    SnapshotStage,
    SnapshotStatus,
)


class IndexStatsResponse(BaseModel):
    files_total: int = 0
    files_parsed: int = 0
    files_reused: int = 0
    symbols: int = 0
    chunks: int = 0
    edges: int = 0
    edges_resolved: int = 0


class CancelIndexingResponse(BaseModel):
    cancelled: bool


class IndexStateResponse(BaseModel):
    """Состояние индекса репозитория.

    Пустой ответ — обычное состояние нового репозитория, а не ошибка:
    ревью в этом случае работает по одному диффу, и клиент должен об этом
    сказать человеку.
    """

    snapshot_id: UUID | None = None
    status: SnapshotStatus | None = None
    stage: SnapshotStage | None = None
    stage_title: str | None = None
    commit_sha: str | None = None
    finished_at: datetime | None = None
    failure_reason: str | None = None
    is_ready: bool = False
    stats: IndexStatsResponse | None = None

    @classmethod
    def from_view(cls, view: IndexStateView) -> "IndexStateResponse":
        return cls(
            snapshot_id=view.snapshot_id,
            status=view.status,
            stage=view.stage,
            stage_title=STAGE_TITLES.get(view.stage) if view.stage else None,
            commit_sha=view.commit_sha,
            finished_at=view.finished_at,
            failure_reason=view.failure_reason,
            is_ready=view.is_ready,
            stats=(
                IndexStatsResponse(
                    files_total=view.stats.files_total,
                    files_parsed=view.stats.files_parsed,
                    files_reused=view.stats.files_reused,
                    symbols=view.stats.symbols,
                    chunks=view.stats.chunks,
                    edges=view.stats.edges,
                    edges_resolved=view.stats.edges_resolved,
                )
                if view.stats
                else None
            ),
        )


class StartIndexingRequest(BaseModel):
    tenant_id: UUID
    revision: str = "HEAD"


class StartIndexingResponse(BaseModel):
    queued: bool
    revision: str
