from collections.abc import (
    Mapping,
)
from typing import (
    Any,
)

from langgraph.runtime import (
    Runtime,
)

from ducktective.core.exceptions import (
    DomainError,
    ReviewInterruptedError,
)
from ducktective.core.review.degradation import (
    NodeDegradation,
    ReviewStage,
    classify_failure,
    failing_model,
)
from ducktective.core.review.ports import (
    CodeReviewer,
    ReviewSupport,
)
from ducktective.core.review.reviewers import (
    ReviewMode,
    review_mode_of,
)
from ducktective.core.review.trace import (
    trace,
)
from ducktective.core.review.value_objects import (
    ReviewLanguage,
)
from ducktective.review_graph.nodes.cancellation import (
    is_cancelled,
)
from ducktective.review_graph.nodes.reporting import (
    report_stage,
)
from ducktective.review_graph.ports import (
    ReviewerNode,
)
from ducktective.review_graph.state import (
    FileDrafts,
    FileReviewTask,
    ReviewRuntimeContext,
)


class UnknownReviewerError(DomainError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Ревьюер {name} не собран в конвейере")
        self.name = name


def review_node(
    reviewers: Mapping[str, CodeReviewer],
) -> ReviewerNode:
    """Отдаёт один файл одному ревьюеру.

    Падение ревьюера не роняет прогон: причина едет дальше вместе с файлом,
    иначе непроверенные файлы неотличимы от файлов без замечаний.
    """

    async def review(
        state: FileReviewTask,
        *,
        runtime: Runtime[ReviewRuntimeContext],
    ) -> dict[str, Any]:
        if await is_cancelled(runtime):
            raise ReviewInterruptedError("Расследование прекращено")

        reviewer = reviewers.get(state.reviewer_name)
        if reviewer is None:
            raise UnknownReviewerError(state.reviewer_name)

        await report_stage(
            runtime,
            f"{_reading(state.reviewer_name, runtime.context.language)}: {state.file.path}",
            file_path=state.file.path,
        )

        try:
            outcome = await reviewer.review_file(
                state.file,
                patch_text=state.file.to_unified_patch(),
                requirements=state.requirements,
                context=state.context,
                support=ReviewSupport(
                    navigator=runtime.context.navigator,
                    sink=runtime.context.sink,
                    cancellation=runtime.context.cancellation,
                    diff=runtime.context.diff,
                    history=runtime.context.history,
                    repository_id=runtime.context.repository_id,
                    language=runtime.context.language,
                ),
            )
        except DomainError as error:
            return _results(
                FileDrafts(
                    **_common(state),
                    degradation=NodeDegradation(
                        stage=ReviewStage.REVIEW,
                        file_path=state.file.path,
                        kind=classify_failure(error),
                        detail=str(error),
                        reviewer=state.reviewer_name,
                        model=failing_model(error),
                    ),
                )
            )

        return _results(
            FileDrafts(
                **_common(state),
                drafts=tuple(outcome.drafts),
                shown=outcome.shown,
                usage=outcome.usage,
            )
        )

    return review


def _reading(reviewer_name: str, language: ReviewLanguage) -> str:
    """Как назвать чтение файла в ленте.

    Режим важен человеку: расследование с инструментами идёт минутами
    и показывает шаги, одноразовый проход молчит до самого ответа.
    """
    if review_mode_of(reviewer_name) is ReviewMode.AGENTIC:
        return trace(language, "reading_agentic")
    return trace(language, "reading_plain")


def _common(task: FileReviewTask) -> dict[str, Any]:
    return {
        "file": task.file,
        "context": task.context,
        "reviewer_name": task.reviewer_name,
    }


def _results(drafts: FileDrafts) -> dict[str, Any]:
    return {"results": [drafts]}
