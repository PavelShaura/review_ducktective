from dataclasses import (
    dataclass,
)

from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.indexing.value_objects import (
    SnapshotStatus,
)
from ducktective.core.types import (
    CommitSha,
    IndexSnapshotId,
    RepositoryId,
)


@dataclass(frozen=True, kw_only=True)
class IndexSnapshotCreated(DomainEvent):
    snapshot_id: IndexSnapshotId
    repository_id: RepositoryId
    commit_sha: CommitSha
    parent_snapshot_id: IndexSnapshotId | None


@dataclass(frozen=True, kw_only=True)
class IndexSnapshotStatusChanged(DomainEvent):
    snapshot_id: IndexSnapshotId
    previous_status: SnapshotStatus
    current_status: SnapshotStatus


@dataclass(frozen=True, kw_only=True)
class SourceFileIndexed(DomainEvent):
    snapshot_id: IndexSnapshotId
    repository_id: RepositoryId
    path: str
    symbols: int
    chunks: int
