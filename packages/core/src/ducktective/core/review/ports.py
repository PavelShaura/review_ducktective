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
from ducktective.core.retrieval.context import (
    DiffContext,
)
from ducktective.core.review.drafts import (
    FindingDraft,
)
from ducktective.core.review.entities import (
    ReviewFile,
    ReviewRun,
)
from ducktective.core.review.pipeline import (
    PipelineOutcome,
    PipelineRequest,
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
        context: DiffContext | None = None,
    ) -> FileReviewResult: ...


class CancellationCheck(Protocol):
    """Спрашивает, не попросили ли прекратить расследование.

    Конвейер отвечает за то, когда спросить, а use case — за то, где хранится
    ответ. Прервать сам запрос к модели нечем, поэтому проверка имеет смысл
    только между файлами.
    """

    async def __call__(self) -> bool: ...


class ReviewPipeline(Protocol):
    """Путь от подготовленных файлов до проверенных находок.

    Объявлен портом, потому что use case зависит от того, что дифф можно
    прогнать через конвейер, но не от того, что конвейер — граф LangGraph.
    """

    async def run(
        self,
        request: PipelineRequest,
        *,
        cancellation: CancellationCheck | None = None,
    ) -> PipelineOutcome: ...
