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
)
from ducktective.review_graph.nodes.cancellation import (
    is_cancelled,
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

        try:
            outcome = await reviewer.review_file(
                state.file,
                patch_text=state.file.to_unified_patch(),
                requirements=state.requirements,
                context=state.context,
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
                usage=outcome.usage,
            )
        )

    return review


def _common(task: FileReviewTask) -> dict[str, Any]:
    return {
        "file": task.file,
        "context": task.context,
        "reviewer_name": task.reviewer_name,
    }


def _results(drafts: FileDrafts) -> dict[str, Any]:
    return {"results": [drafts]}
