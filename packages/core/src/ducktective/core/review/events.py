from dataclasses import (
    dataclass,
)

from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.review.value_objects import (
    FeedbackVerdict,
    FindingCategory,
    ReviewStatus,
    Severity,
)
from ducktective.core.types import (
    FindingId,
    RepositoryId,
    ReviewRunId,
)


@dataclass(frozen=True, kw_only=True)
class ReviewRunCreated(DomainEvent):
    run_id: ReviewRunId
    repository_id: RepositoryId
    base_sha: str
    head_sha: str
    reviewable_files: int


@dataclass(frozen=True, kw_only=True)
class ReviewRunStatusChanged(DomainEvent):
    run_id: ReviewRunId
    previous_status: ReviewStatus
    current_status: ReviewStatus


@dataclass(frozen=True, kw_only=True)
class FindingFeedbackSubmitted(DomainEvent):
    run_id: ReviewRunId
    finding_id: FindingId
    verdict: FeedbackVerdict


@dataclass(frozen=True, kw_only=True)
class FindingRecorded(DomainEvent):
    run_id: ReviewRunId
    finding_id: FindingId
    severity: Severity
    category: FindingCategory
    file_path: str
