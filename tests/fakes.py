from pathlib import (
    Path,
)
from types import (
    TracebackType,
)
from typing import (
    Any,
    Self,
)

from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
    LlmInvocationError,
    VcsOperationError,
)
from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmResponse,
    LlmUsage,
    ModelRequirements,
)
from ducktective.core.review.drafts import (
    FindingDraft,
)
from ducktective.core.review.entities import (
    ReviewFile,
    ReviewRun,
)
from ducktective.core.review.ports import (
    FileReviewResult,
)
from ducktective.core.types import (
    CommitSha,
    RepositoryId,
    ReviewRunId,
    TenantId,
)


class FakeCodeRepositoryRepository:
    def __init__(self) -> None:
        self.stored: dict[RepositoryId, CodeRepository] = {}

    def add(self, repository: CodeRepository) -> None:
        self.stored[repository.id] = repository

    async def get(self, repository_id: RepositoryId) -> CodeRepository:
        repository = self.stored.get(repository_id)
        if repository is None:
            raise EntityNotFoundError("CodeRepository", repository_id)
        return repository

    async def find_by_name(self, tenant_id: TenantId, name: str) -> CodeRepository | None:
        for repository in self.stored.values():
            if repository.tenant_id == tenant_id and repository.name == name:
                return repository
        return None

    async def list_for_tenant(self, tenant_id: TenantId) -> list[CodeRepository]:
        return [
            repository for repository in self.stored.values() if repository.tenant_id == tenant_id
        ]


class FakeReviewRunRepository:
    def __init__(self) -> None:
        self.stored: dict[ReviewRunId, ReviewRun] = {}
        self.removed_events: list[DomainEvent] = []

    def add(self, run: ReviewRun) -> None:
        self.stored[run.id] = run

    async def get(self, run_id: ReviewRunId) -> ReviewRun:
        run = self.stored.get(run_id)
        if run is None:
            raise EntityNotFoundError("ReviewRun", run_id)
        return run

    async def list_for_repository(
        self,
        repository_id: RepositoryId,
        *,
        limit: int = 50,
    ) -> list[ReviewRun]:
        runs = [run for run in self.stored.values() if run.repository_id == repository_id]
        return runs[:limit]

    async def remove(self, run: ReviewRun) -> None:
        self.stored.pop(run.id, None)
        self.removed_events.extend(run.pull_events())


class FakeUnitOfWork:
    """Unit of Work на словарях: позволяет тестировать use cases без БД."""

    def __init__(self) -> None:
        self.code_repositories = FakeCodeRepositoryRepository()
        self.review_runs = FakeReviewRunRepository()
        self.commit_calls = 0
        self.rollback_calls = 0
        self.is_active = False

    async def __aenter__(self) -> Self:
        self.is_active = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.is_active = False

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1

    def collect_events(self) -> list[DomainEvent]:
        collected = self.review_runs.removed_events
        self.review_runs.removed_events = []
        for repository in self.code_repositories.stored.values():
            collected.extend(repository.pull_events())
        for run in self.review_runs.stored.values():
            collected.extend(run.pull_events())
        return collected


class FakeEventPublisher:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    async def publish(self, events: list[DomainEvent]) -> None:
        self.published.extend(events)


class FakeLlmClient:
    """Клиент модели, отдающий заранее заданный ответ."""

    def __init__(self, content: str = '{"findings": []}', *, usage: LlmUsage | None = None) -> None:
        self.content = content
        self.usage = usage or LlmUsage(input_tokens=100, output_tokens=50)
        self.calls: list[list[LlmMessage]] = []

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        requirements: ModelRequirements,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        self.calls.append(messages)
        return LlmResponse(
            content=self.content,
            model="fake-model",
            provider="fake",
            usage=self.usage,
        )


class FakeCodeReviewer:
    """Ревьюер, возвращающий заранее заданные черновики находок."""

    name = "reviewer:fake"

    def __init__(
        self,
        drafts_by_path: dict[str, list[FindingDraft]] | None = None,
        *,
        failing_paths: set[str] | None = None,
    ) -> None:
        self.drafts_by_path = drafts_by_path or {}
        self.failing_paths = failing_paths or set()
        self.reviewed_paths: list[str] = []

    async def review_file(
        self,
        file: ReviewFile,
        *,
        patch_text: str,
        requirements: ModelRequirements,
    ) -> FileReviewResult:
        if file.path in self.failing_paths:
            raise LlmInvocationError(f"Модель недоступна для {file.path}")

        self.reviewed_paths.append(file.path)
        return FileReviewResult(
            drafts=self.drafts_by_path.get(file.path, []),
            usage=LlmUsage(input_tokens=100, output_tokens=25),
            model="fake-model",
        )


class FakeVcsProvider:
    """Git-провайдер, отдающий заранее заданный патч."""

    def __init__(
        self,
        patch_text: str = "",
        *,
        known_revisions: set[str] | None = None,
        file_contents: dict[str, str] | None = None,
        staged_patch_text: str | None = None,
    ) -> None:
        self.patch_text = patch_text
        self.staged_patch_text = staged_patch_text
        self.known_revisions = known_revisions
        self.file_contents = file_contents or {}
        self.requested_paths: list[Path] = []

    async def resolve_revision(self, repository_path: Path, revision: str) -> CommitSha:
        if self.known_revisions is not None and revision not in self.known_revisions:
            raise VcsOperationError(f"Ревизия не найдена: {revision}")
        return CommitSha(f"sha-{revision}")

    async def get_patch(
        self,
        repository_path: Path,
        *,
        base: str,
        head: str,
        use_merge_base: bool = True,
    ) -> str:
        self.requested_paths.append(repository_path)
        return self.patch_text

    async def get_staged_patch(self, repository_path: Path) -> str:
        self.requested_paths.append(repository_path)
        return self.staged_patch_text if self.staged_patch_text is not None else self.patch_text

    async def get_file_content(
        self,
        repository_path: Path,
        *,
        revision: str,
        path: str,
    ) -> str | None:
        return self.file_contents.get(path)
