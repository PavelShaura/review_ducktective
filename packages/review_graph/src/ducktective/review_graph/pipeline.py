from collections.abc import (
    Iterable,
)

from ducktective.core.llm.value_objects import (
    LlmUsage,
)
from ducktective.core.retrieval.ports import (
    ContextBuilder,
)
from ducktective.core.review.pipeline import (
    PipelineOutcome,
    PipelineRequest,
)
from ducktective.core.review.ports import (
    CancellationCheck,
    CodeReviewer,
)
from ducktective.review_graph.const import (
    DEFAULT_MAX_CONCURRENT_REVIEWS,
)
from ducktective.review_graph.graph import (
    build_review_graph,
)
from ducktective.review_graph.state import (
    FileDrafts,
    ReviewGraphState,
    ReviewRuntimeContext,
)


class LangGraphReviewPipeline:
    """Реализация порта `ReviewPipeline` поверх LangGraph.

    Граф компилируется один раз на приложение: зависимости узлов от прогона
    не зависят, а всё, что меняется, приходит состоянием и контекстом запуска.
    """

    def __init__(
        self,
        reviewers: Iterable[CodeReviewer],
        *,
        context_builder: ContextBuilder | None = None,
        max_concurrent_reviews: int = DEFAULT_MAX_CONCURRENT_REVIEWS,
    ) -> None:
        self._reviewers = {reviewer.name: reviewer for reviewer in reviewers}
        self._max_concurrent_reviews = max_concurrent_reviews
        self._graph = build_review_graph(self._reviewers, context_builder=context_builder)

    async def run(
        self,
        request: PipelineRequest,
        *,
        cancellation: CancellationCheck | None = None,
    ) -> PipelineOutcome:
        raw = await self._graph.ainvoke(
            ReviewGraphState(request=request),
            context=ReviewRuntimeContext(cancellation=cancellation),
            config={"max_concurrency": self._max_concurrent_reviews},
        )
        state = ReviewGraphState.model_validate(raw)

        return PipelineOutcome(
            findings=state.findings,
            usage=_total_usage(state.results),
            proposed=state.proposed,
            discarded_outside_diff=state.discarded_outside_diff,
            discarded_without_evidence=state.discarded_without_evidence,
            discarded_as_duplicate=state.discarded_as_duplicate,
            failed_files=tuple(item.failure for item in state.results if item.failure),
            files_with_context=state.files_with_context,
            reviewed_files=sum(
                1 for item in state.results if item.failure is None and not item.is_cancelled
            ),
            is_cancelled=any(item.is_cancelled for item in state.results),
        )


def _total_usage(results: list[FileDrafts]) -> LlmUsage:
    total = LlmUsage()
    for item in results:
        total = LlmUsage(
            input_tokens=total.input_tokens + item.usage.input_tokens,
            output_tokens=total.output_tokens + item.usage.output_tokens,
            cost_usd=total.cost_usd + item.usage.cost_usd,
        )
    return total
