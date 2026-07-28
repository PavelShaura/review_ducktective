from collections import (
    Counter,
)
from dataclasses import (
    dataclass,
    field,
)
from datetime import (
    UTC,
    datetime,
)
from typing import (
    Self,
)
from uuid import (
    uuid4,
)

from ducktective.core.aggregate import (
    AggregateRoot,
)
from ducktective.core.diff.entities import (
    Diff,
    DiffFile,
)
from ducktective.core.diff.value_objects import (
    ChangeType,
    DiffSide,
    LineRange,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
    InvariantViolationError,
)
from ducktective.core.llm.value_objects import (
    LlmUsage,
)
from ducktective.core.review.events import (
    FindingFeedbackSubmitted,
    FindingRecorded,
    ReviewRunCreated,
    ReviewRunDeleted,
    ReviewRunStatusChanged,
)
from ducktective.core.review.limits import (
    MAX_DISPLAYABLE_PATCH_BYTES,
    MAX_DISPLAYABLE_PATCH_LINES,
)
from ducktective.core.review.value_objects import (
    RESTARTABLE_STATUSES,
    TERMINAL_STATUSES,
    EvidenceKind,
    FeedbackVerdict,
    FindingCategory,
    FindingProducer,
    FindingStatus,
    ReviewSource,
    ReviewStatus,
    Severity,
)
from ducktective.core.types import (
    CommitSha,
    FindingFeedbackId,
    FindingId,
    RepositoryId,
    ReviewFileId,
    ReviewHunkId,
    ReviewRunId,
    TenantId,
    UserId,
)


@dataclass(kw_only=True)
class ReviewHunk:
    id: ReviewHunkId
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    header: str
    patch_text: str

    @property
    def new_range(self) -> LineRange | None:
        if self.new_lines == 0:
            return None
        return LineRange(start=self.new_start, end=self.new_start + self.new_lines - 1)


@dataclass(kw_only=True)
class ReviewFile:
    id: ReviewFileId
    path: str
    previous_path: str | None
    change_type: ChangeType
    language: str | None
    added_lines: int
    removed_lines: int
    hunks: list[ReviewHunk] = field(default_factory=list)

    def covers_line(self, line: int) -> bool:
        return any(
            hunk.new_range is not None and hunk.new_range.contains(line) for hunk in self.hunks
        )

    def to_unified_patch(self) -> str:
        """Собирает патч файла целиком.

        Формат совпадает с выводом git diff: клиентские библиотеки разбора диффа
        ожидают заголовок с путями, а не отдельные блоки изменений.
        """
        if not self.hunks:
            return ""

        source_path = self.previous_path or self.path
        header_lines = [
            f"diff --git a/{source_path} b/{self.path}",
            "--- /dev/null" if self.change_type is ChangeType.ADDED else f"--- a/{source_path}",
            "+++ /dev/null" if self.change_type is ChangeType.DELETED else f"+++ b/{self.path}",
        ]
        body = "".join(_ensure_trailing_newline(hunk.patch_text) for hunk in self.hunks)
        return "\n".join(header_lines) + "\n" + body

    @property
    def patch_size_bytes(self) -> int:
        return sum(len(hunk.patch_text.encode("utf-8")) for hunk in self.hunks)

    @property
    def patch_line_count(self) -> int:
        return sum(hunk.patch_text.count("\n") + 1 for hunk in self.hunks)

    @property
    def is_too_large_to_display(self) -> bool:
        """Слишком большие файлы не отдаются целиком: браузер не справится.

        Тот же признак используется для исключения файла из ревью моделью.
        """
        return (
            self.patch_size_bytes > MAX_DISPLAYABLE_PATCH_BYTES
            or self.patch_line_count > MAX_DISPLAYABLE_PATCH_LINES
        )


@dataclass(kw_only=True)
class Evidence:
    kind: EvidenceKind
    file_path: str
    snippet: str
    line_start: int | None = None
    line_end: int | None = None


@dataclass(kw_only=True)
class FindingFeedback:
    """Оценка находки человеком.

    Хранится журналом, а не одним значением: смена мнения — тоже полезный сигнал
    при разборе качества.
    """

    id: FindingFeedbackId
    verdict: FeedbackVerdict
    created_at: datetime
    user_id: UserId | None = None
    comment: str | None = None


@dataclass(kw_only=True)
class Finding:
    id: FindingId
    file_path: str
    line_start: int
    line_end: int
    side: DiffSide
    severity: Severity
    category: FindingCategory
    title: str
    body_markdown: str
    dedup_key: str
    producer: FindingProducer
    producer_name: str
    rule_id: str | None = None
    suggested_patch: str | None = None
    confidence: float | None = None
    status: FindingStatus = FindingStatus.PROPOSED
    evidence: list[Evidence] = field(default_factory=list)
    feedback: list[FindingFeedback] = field(default_factory=list)

    @property
    def has_evidence(self) -> bool:
        return bool(self.evidence)

    @property
    def latest_feedback(self) -> FindingFeedback | None:
        if not self.feedback:
            return None
        return max(self.feedback, key=lambda item: item.created_at)

    @property
    def latest_verdict(self) -> FeedbackVerdict | None:
        entry = self.latest_feedback
        return None if entry is None else entry.verdict

    def record_feedback(
        self,
        verdict: FeedbackVerdict,
        *,
        user_id: UserId | None = None,
        comment: str | None = None,
    ) -> FindingFeedback:
        """Фиксирует оценку и приводит статус в соответствие с ней.

        Отметка «ложное срабатывание» отклоняет находку, а любая другая снимает
        отклонение: мнение можно изменить, и находка должна вернуться в работу.
        """
        entry = FindingFeedback(
            id=FindingFeedbackId(uuid4()),
            verdict=verdict,
            created_at=datetime.now(UTC),
            user_id=user_id,
            comment=comment,
        )
        self.feedback.append(entry)

        if verdict is FeedbackVerdict.FALSE_POSITIVE:
            self.status = FindingStatus.REJECTED
        elif self.status is FindingStatus.REJECTED:
            self.status = FindingStatus.VERIFIED if self.has_evidence else FindingStatus.PROPOSED

        return entry

    def verify(self) -> None:
        """Подтверждает находку. Без доказательств подтверждение невозможно."""
        if not self.has_evidence:
            raise InvariantViolationError(
                f"Находка «{self.title}» не может быть подтверждена без доказательств"
            )
        self.status = FindingStatus.VERIFIED

    def reject(self) -> None:
        self.status = FindingStatus.REJECTED


@dataclass(kw_only=True)
class ReviewRun(AggregateRoot):
    """Прогон ревью.

    Агрегирует разобранный дифф и найденные проблемы: находка не существует
    вне прогона, а статистика по уровням всегда согласована со списком находок.
    """

    id: ReviewRunId
    tenant_id: TenantId
    repository_id: RepositoryId
    source: ReviewSource
    base_sha: CommitSha
    head_sha: CommitSha
    status: ReviewStatus
    created_at: datetime
    created_by: UserId | None = None
    external_pull_request_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_reason: str | None = None
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    files_with_context: int = 0
    files: list[ReviewFile] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        source: ReviewSource,
        diff: Diff,
        created_by: UserId | None = None,
        external_pull_request_id: str | None = None,
    ) -> Self:
        if diff.is_empty:
            raise InvariantViolationError("Дифф пуст: ревьюить нечего")

        run = cls(
            id=ReviewRunId(uuid4()),
            tenant_id=tenant_id,
            repository_id=repository_id,
            source=source,
            base_sha=diff.base_sha,
            head_sha=diff.head_sha,
            status=ReviewStatus.QUEUED,
            created_at=datetime.now(UTC),
            created_by=created_by,
            external_pull_request_id=external_pull_request_id,
            files=[_build_file(diff_file) for diff_file in diff.files],
        )
        run.record_event(
            ReviewRunCreated(
                run_id=run.id,
                repository_id=run.repository_id,
                base_sha=run.base_sha,
                head_sha=run.head_sha,
                reviewable_files=len(diff.reviewable_files()),
            )
        )
        return run

    @property
    def is_finished(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def severity_totals(self) -> dict[str, int]:
        """Сводка активных находок: отклонённые внимания больше не требуют."""
        counter = Counter(
            finding.severity.value
            for finding in self.findings
            if finding.status is not FindingStatus.REJECTED
        )
        return dict(counter)

    @property
    def severity_counts(self) -> dict[str, int]:
        """Разбивка всех находок, включая отклонённые.

        Нужна там, где число должно совпадать с тем, что человек видит
        на странице прогона: отклонённые никуда не исчезают.
        """
        return dict(Counter(finding.severity.value for finding in self.findings))

    @property
    def rejected_count(self) -> int:
        return sum(1 for finding in self.findings if finding.status is FindingStatus.REJECTED)

    def mark_running(self) -> None:
        self._change_status(ReviewStatus.RUNNING)
        self.started_at = datetime.now(UTC)

    def mark_completed(self) -> None:
        self._change_status(ReviewStatus.COMPLETED)
        self.finished_at = datetime.now(UTC)

    def mark_failed(self, reason: str) -> None:
        self._change_status(ReviewStatus.FAILED)
        self.failure_reason = reason
        self.finished_at = datetime.now(UTC)

    def cancel(self) -> None:
        """Прекращает прогон по просьбе человека.

        Найденное не сохраняется: находки пишутся одной транзакцией в конце,
        а половина ревью — это не половина результата, потому что дубли
        отсеиваются по всему набору сразу.
        """
        self._change_status(ReviewStatus.CANCELLED)
        self.finished_at = datetime.now(UTC)

    @property
    def is_cancelled(self) -> bool:
        return self.status is ReviewStatus.CANCELLED

    @property
    def is_restartable(self) -> bool:
        return self.status in RESTARTABLE_STATUSES

    def restart(self) -> None:
        """Возвращает прекращённый или неудавшийся прогон в очередь.

        Расследование начинается с начала: сохранять было нечего, а счётчики
        токенов обнуляются, чтобы цифры прогона описывали одну попытку,
        а не сумму всех.
        """
        if not self.is_restartable:
            raise InvariantViolationError(
                f"Прогон в статусе {self.status} нельзя отправить на расследование заново"
            )

        previous_status = self.status
        self.status = ReviewStatus.QUEUED
        self.started_at = None
        self.finished_at = None
        self.failure_reason = None
        self.tokens_input = 0
        self.tokens_output = 0
        self.cost_usd = 0.0
        self.files_with_context = 0
        self.record_event(
            ReviewRunStatusChanged(
                run_id=self.id,
                previous_status=previous_status,
                current_status=ReviewStatus.QUEUED,
            )
        )

    def add_finding(self, finding: Finding) -> bool:
        """Добавляет находку, отбрасывая дубли по ключу дедупликации.

        Возвращает признак того, что находка действительно добавлена.
        """
        if self.is_finished:
            raise InvariantViolationError("Прогон завершён: находки больше не принимаются")
        if any(existing.dedup_key == finding.dedup_key for existing in self.findings):
            return False

        self.findings.append(finding)
        self.record_event(
            FindingRecorded(
                run_id=self.id,
                finding_id=finding.id,
                severity=finding.severity,
                category=finding.category,
                file_path=finding.file_path,
            )
        )
        return True

    def record_context_usage(self, files_with_context: int) -> None:
        """Запоминает, для скольких файлов нашлось окружение из индекса.

        Ревью без индекса работает по одному диффу и находит заметно меньше.
        Без этого числа разница в качестве выглядит случайностью, а не
        следствием того, был ли собран индекс.
        """
        self.files_with_context = files_with_context

    def record_usage(self, usage: LlmUsage) -> None:
        self.tokens_input += usage.input_tokens
        self.tokens_output += usage.output_tokens
        self.cost_usd += usage.cost_usd

    def reviewable_files(self) -> list[ReviewFile]:
        """Файлы, которые имеет смысл отдавать модели.

        Удалённые файлы и слишком большие патчи исключаются: первые нечего
        ревьюить, вторые не влезут в контекст и стоят непропорционально дорого.
        """
        return [
            file
            for file in self.files
            if file.change_type is not ChangeType.DELETED
            and file.hunks
            and not file.is_too_large_to_display
        ]

    def submit_feedback(
        self,
        finding_id: FindingId,
        verdict: FeedbackVerdict,
        *,
        user_id: UserId | None = None,
        comment: str | None = None,
    ) -> FindingFeedback:
        finding = self.find_finding(finding_id)
        if finding is None:
            raise EntityNotFoundError("Finding", finding_id)

        entry = finding.record_feedback(verdict, user_id=user_id, comment=comment)
        self.record_event(
            FindingFeedbackSubmitted(
                run_id=self.id,
                finding_id=finding_id,
                verdict=verdict,
            )
        )
        return entry

    def record_deletion(self) -> None:
        """Отмечает удаление прогона.

        Событие порождается до фактического удаления: после него агрегата
        уже не существует, а подписчикам знать о случившемся нужно.
        """
        self.record_event(ReviewRunDeleted(run_id=self.id, repository_id=self.repository_id))

    def find_finding(self, finding_id: FindingId) -> Finding | None:
        for finding in self.findings:
            if finding.id == finding_id:
                return finding
        return None

    def find_file(self, path: str) -> ReviewFile | None:
        for file in self.files:
            if file.path == path:
                return file
        return None

    def find_file_by_id(self, file_id: ReviewFileId) -> ReviewFile | None:
        for file in self.files:
            if file.id == file_id:
                return file
        return None

    def _change_status(self, status: ReviewStatus) -> None:
        if self.is_finished:
            raise InvariantViolationError(
                f"Прогон уже завершён со статусом {self.status}, переход в {status} невозможен"
            )
        if status is self.status:
            return

        previous_status = self.status
        self.status = status
        self.record_event(
            ReviewRunStatusChanged(
                run_id=self.id,
                previous_status=previous_status,
                current_status=status,
            )
        )


def _ensure_trailing_newline(text: str) -> str:
    return text if text.endswith("\n") else f"{text}\n"


def _build_file(diff_file: DiffFile) -> ReviewFile:
    return ReviewFile(
        id=ReviewFileId(uuid4()),
        path=diff_file.path,
        previous_path=diff_file.previous_path,
        change_type=diff_file.change_type,
        language=diff_file.language,
        added_lines=diff_file.added_lines,
        removed_lines=diff_file.removed_lines,
        hunks=[
            ReviewHunk(
                id=ReviewHunkId(uuid4()),
                old_start=hunk.old_start,
                old_lines=hunk.old_lines,
                new_start=hunk.new_start,
                new_lines=hunk.new_lines,
                header=hunk.header,
                patch_text=hunk.patch_text,
            )
            for hunk in diff_file.hunks
        ],
    )
