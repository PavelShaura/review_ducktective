from dataclasses import (
    dataclass,
)
from typing import (
    Protocol,
)

from ducktective.core.llm.value_objects import (
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
from ducktective.core.types import (
    RepositoryId,
    ReviewRunId,
)


class ReviewRunRepository(Protocol):
    """Доступ к агрегату ReviewRun. Транзакцию не фиксирует."""

    def add(self, run: ReviewRun) -> None: ...

    async def get(self, run_id: ReviewRunId) -> ReviewRun: ...

    async def list_for_repository(
        self,
        repository_id: RepositoryId,
        *,
        limit: int = 50,
    ) -> list[ReviewRun]: ...

    async def remove(self, run: ReviewRun) -> None: ...


@dataclass(frozen=True, kw_only=True)
class FileReviewResult:
    drafts: list[FindingDraft]
    usage: LlmUsage
    model: str
    is_cache_hit: bool = False


class CodeReviewer(Protocol):
    """Ревьюер одного файла. Реализация решает, чем именно он думает."""

    name: str

    async def review_file(
        self,
        file: ReviewFile,
        *,
        patch_text: str,
        requirements: ModelRequirements,
    ) -> FileReviewResult: ...
