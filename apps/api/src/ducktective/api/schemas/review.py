from datetime import (
    datetime,
)
from uuid import (
    UUID,
)

from pydantic import (
    BaseModel,
    Field,
)

from ducktective.application.review.views import (
    FileContextView,
    FilePatchView,
)
from ducktective.core.diff.value_objects import (
    ChangeType,
    DiffSide,
)
from ducktective.core.review.entities import (
    Finding,
    FindingFeedback,
    ReviewFile,
    ReviewHunk,
    ReviewRun,
)
from ducktective.core.review.value_objects import (
    FeedbackVerdict,
    FindingCategory,
    FindingStatus,
    ReviewSource,
    ReviewStatus,
    Severity,
)


class StartReviewRequest(BaseModel):
    tenant_id: UUID
    base: str = Field(min_length=1, max_length=255)
    head: str = Field(default="HEAD", min_length=1, max_length=255)
    source: ReviewSource = ReviewSource.LOCAL_DIFF
    external_pull_request_id: str | None = None


class HunkResponse(BaseModel):
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    header: str

    @classmethod
    def from_domain(cls, hunk: ReviewHunk) -> "HunkResponse":
        return cls(
            old_start=hunk.old_start,
            old_lines=hunk.old_lines,
            new_start=hunk.new_start,
            new_lines=hunk.new_lines,
            header=hunk.header,
        )


class ReviewFileResponse(BaseModel):
    id: UUID
    path: str
    previous_path: str | None
    change_type: ChangeType
    language: str | None
    added_lines: int
    removed_lines: int
    is_too_large: bool
    hunks: list[HunkResponse]

    @classmethod
    def from_domain(cls, file: ReviewFile) -> "ReviewFileResponse":
        return cls(
            id=file.id,
            path=file.path,
            previous_path=file.previous_path,
            change_type=file.change_type,
            language=file.language,
            added_lines=file.added_lines,
            removed_lines=file.removed_lines,
            is_too_large=file.is_too_large_to_display,
            hunks=[HunkResponse.from_domain(hunk) for hunk in file.hunks],
        )


class FilePatchResponse(BaseModel):
    path: str
    previous_path: str | None
    change_type: ChangeType
    language: str | None
    added_lines: int
    removed_lines: int
    is_too_large: bool
    patch_size_bytes: int
    patch: str

    @classmethod
    def from_view(cls, view: FilePatchView) -> "FilePatchResponse":
        return cls(
            path=view.path,
            previous_path=view.previous_path,
            change_type=view.change_type,
            language=view.language,
            added_lines=view.added_lines,
            removed_lines=view.removed_lines,
            is_too_large=view.is_too_large,
            patch_size_bytes=view.patch_size_bytes,
            patch=view.patch,
        )


class FileContextResponse(BaseModel):
    path: str
    side: DiffSide
    commit_sha: str
    start_line: int
    end_line: int
    total_lines: int
    lines: list[str]

    @classmethod
    def from_view(cls, view: FileContextView) -> "FileContextResponse":
        return cls(
            path=view.path,
            side=view.side,
            commit_sha=view.commit_sha,
            start_line=view.start_line,
            end_line=view.end_line,
            total_lines=view.total_lines,
            lines=view.lines,
        )


class SubmitFeedbackRequest(BaseModel):
    tenant_id: UUID
    verdict: FeedbackVerdict
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    id: UUID
    verdict: FeedbackVerdict
    comment: str | None
    created_at: datetime

    @classmethod
    def from_domain(cls, feedback: FindingFeedback) -> "FeedbackResponse":
        return cls(
            id=feedback.id,
            verdict=feedback.verdict,
            comment=feedback.comment,
            created_at=feedback.created_at,
        )


class FindingResponse(BaseModel):
    id: UUID
    file_path: str
    line_start: int
    line_end: int
    side: DiffSide
    severity: Severity
    category: FindingCategory
    status: FindingStatus
    title: str
    body_markdown: str
    suggested_patch: str | None
    confidence: float | None
    producer_name: str
    latest_verdict: FeedbackVerdict | None

    @classmethod
    def from_domain(cls, finding: Finding) -> "FindingResponse":
        return cls(
            id=finding.id,
            latest_verdict=finding.latest_verdict,
            file_path=finding.file_path,
            line_start=finding.line_start,
            line_end=finding.line_end,
            side=finding.side,
            severity=finding.severity,
            category=finding.category,
            status=finding.status,
            title=finding.title,
            body_markdown=finding.body_markdown,
            suggested_patch=finding.suggested_patch,
            confidence=finding.confidence,
            producer_name=finding.producer_name,
        )


class ReviewRunResponse(BaseModel):
    id: UUID
    repository_id: UUID
    source: ReviewSource
    status: ReviewStatus
    base_sha: str
    head_sha: str
    totals: dict[str, int]
    failure_reason: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    files: list[ReviewFileResponse]
    findings: list[FindingResponse]

    @classmethod
    def from_domain(cls, run: ReviewRun) -> "ReviewRunResponse":
        return cls(
            id=run.id,
            repository_id=run.repository_id,
            source=run.source,
            status=run.status,
            base_sha=run.base_sha,
            head_sha=run.head_sha,
            totals=run.severity_totals,
            failure_reason=run.failure_reason,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            files=[ReviewFileResponse.from_domain(file) for file in run.files],
            findings=[FindingResponse.from_domain(finding) for finding in run.findings],
        )


class ReviewRunSummary(BaseModel):
    id: UUID
    repository_id: UUID
    status: ReviewStatus
    base_sha: str
    head_sha: str
    totals: dict[str, int]
    severity_counts: dict[str, int]
    findings_total: int
    rejected_count: int
    created_at: datetime
    changed_files: int

    @classmethod
    def from_domain(cls, run: ReviewRun) -> "ReviewRunSummary":
        return cls(
            id=run.id,
            repository_id=run.repository_id,
            status=run.status,
            base_sha=run.base_sha,
            head_sha=run.head_sha,
            totals=run.severity_totals,
            severity_counts=run.severity_counts,
            findings_total=len(run.findings),
            rejected_count=run.rejected_count,
            created_at=run.created_at,
            changed_files=len(run.files),
        )
