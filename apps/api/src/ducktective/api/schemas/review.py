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

from ducktective.application.review.read_investigation import (
    InvestigationStepView,
    InvestigationView,
)
from ducktective.application.review.views import (
    FeedbackDigestView,
    FileContextView,
    FilePatchView,
    MarkedFindingView,
)
from ducktective.core.diff.value_objects import (
    ChangeType,
    DiffSide,
)
from ducktective.core.review.degradation import (
    DegradationKind,
    NodeDegradation,
    ReviewStage,
)
from ducktective.core.review.entities import (
    Finding,
    FindingFeedback,
    ReviewFile,
    ReviewHunk,
    ReviewRun,
)
from ducktective.core.review.investigation import (
    StepKind,
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
    context_side: DiffSide
    total_lines: int | None

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
            context_side=view.context_side,
            total_lines=view.total_lines,
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


class MarkedFindingResponse(BaseModel):
    run_id: UUID
    finding_id: UUID
    file_path: str
    line_start: int
    severity: Severity
    category: FindingCategory
    title: str
    producer_name: str
    verdict: FeedbackVerdict
    comment: str | None
    marked_at: datetime

    @classmethod
    def from_view(cls, view: MarkedFindingView) -> "MarkedFindingResponse":
        return cls(
            run_id=view.run_id,
            finding_id=view.finding_id,
            file_path=view.file_path,
            line_start=view.line_start,
            severity=view.severity,
            category=view.category,
            title=view.title,
            producer_name=view.producer_name,
            verdict=view.verdict,
            comment=view.comment,
            marked_at=view.marked_at,
        )


class FeedbackDigestResponse(BaseModel):
    marked: list[MarkedFindingResponse]
    counts: dict[str, int]
    marked_count: int
    total_findings: int
    useful_share: float | None

    @classmethod
    def from_view(cls, view: FeedbackDigestView) -> "FeedbackDigestResponse":
        return cls(
            marked=[MarkedFindingResponse.from_view(item) for item in view.marked],
            counts=view.counts,
            marked_count=view.marked_count,
            total_findings=view.total_findings,
            useful_share=view.useful_share,
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


class CancelRunResponse(BaseModel):
    """Признак того, что просьбу приняли.

    Ложь означает, что прогон уже завершился сам, — это не ошибка,
    а гонка между кнопкой и последним файлом.
    """

    cancelled: bool


class NodeDegradationResponse(BaseModel):
    """Один сбой: кто, где и почему не отработал.

    Вид причины приходит с сервера отдельным полем, а не вычитывается
    клиентом из текста: разбирать готовую фразу регуляркой — значит
    ломать интерфейс каждой правкой формулировки.
    """

    stage: ReviewStage
    file_path: str
    kind: DegradationKind
    detail: str
    reviewer: str | None
    model: str | None

    @classmethod
    def from_domain(cls, mark: NodeDegradation) -> "NodeDegradationResponse":
        return cls(
            stage=mark.stage,
            file_path=mark.file_path,
            kind=mark.kind,
            detail=mark.detail,
            reviewer=mark.reviewer,
            model=mark.model,
        )


class ReviewRunResponse(BaseModel):
    """Прогон целиком.

    `reviewable_files` — сколько файлов вообще отдавалось модели. Правило отбора
    живёт в домене и исключает не только слишком большие патчи, но и удалённые
    файлы. Клиенту его неоткуда знать, а считая по-своему, он делит одно число
    на другое из другого счёта.
    """

    id: UUID
    repository_id: UUID
    source: ReviewSource
    status: ReviewStatus
    base_sha: str
    head_sha: str
    head_subject: str | None
    totals: dict[str, int]
    failure_reason: str | None
    degradations: list[NodeDegradationResponse]
    duration_ms: int
    files_with_context: int
    reviewable_files: int
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
            head_subject=run.head_subject,
            totals=run.severity_totals,
            failure_reason=run.failure_reason,
            degradations=[NodeDegradationResponse.from_domain(mark) for mark in run.degradations],
            duration_ms=run.duration_ms,
            files_with_context=run.files_with_context,
            reviewable_files=len(run.reviewable_files()),
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
    head_subject: str | None
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
            head_subject=run.head_subject,
            totals=run.severity_totals,
            severity_counts=run.severity_counts,
            findings_total=len(run.findings),
            rejected_count=run.rejected_count,
            created_at=run.created_at,
            changed_files=len(run.files),
        )


class InvestigationStepResponse(BaseModel):
    """Шаг расследования для ленты в интерфейсе."""

    cursor: int
    file_path: str
    number: int
    kind: StepKind
    tool_name: str | None
    arguments: str | None
    detail: str
    duration_ms: int
    is_error: bool

    @classmethod
    def from_view(cls, view: InvestigationStepView) -> "InvestigationStepResponse":
        return cls(
            cursor=view.cursor,
            file_path=view.file_path,
            number=view.number,
            kind=view.kind,
            tool_name=view.tool_name,
            arguments=view.arguments,
            detail=view.detail,
            duration_ms=view.duration_ms,
            is_error=view.is_error,
        )


class InvestigationResponse(BaseModel):
    """Кусок ленты вместе с местом, с которого её продолжать.

    Курсор возвращается всегда, в том числе для пустого куска: иначе клиент,
    догнавший конец ленты, при следующем опросе прочитал бы её сначала.
    """

    steps: list[InvestigationStepResponse]
    next_cursor: int

    @classmethod
    def from_view(cls, view: InvestigationView) -> "InvestigationResponse":
        return cls(
            steps=[InvestigationStepResponse.from_view(step) for step in view.steps],
            next_cursor=view.next_cursor,
        )
