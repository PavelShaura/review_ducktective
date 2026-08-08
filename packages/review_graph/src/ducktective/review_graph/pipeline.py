from collections.abc import (
    Iterable,
)
from typing import (
    Any,
)

from langchain_core.runnables import (
    RunnableConfig,
)
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
)

from ducktective.core.exceptions import (
    ReviewInterruptedError,
)
from ducktective.core.llm.value_objects import (
    LlmUsage,
)
from ducktective.core.retrieval.navigation import (
    CodeNavigator,
)
from ducktective.core.retrieval.ports import (
    ContextBuilder,
)
from ducktective.core.review.degradation import (
    NodeDegradation,
)
from ducktective.core.review.investigation import (
    InvestigationSink,
    InvestigationSinks,
)
from ducktective.core.review.pipeline import (
    PipelineOutcome,
    PipelineRequest,
)
from ducktective.core.review.ports import (
    CancellationCheck,
    CodeReviewer,
    ReviewNavigators,
)
from ducktective.core.types import (
    ReviewRunId,
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
        navigators: ReviewNavigators | None = None,
        sinks: InvestigationSinks | None = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        max_concurrent_reviews: int = DEFAULT_MAX_CONCURRENT_REVIEWS,
    ) -> None:
        self._reviewers = {reviewer.name: reviewer for reviewer in reviewers}
        self._navigators = navigators
        self._sinks = sinks
        self._max_concurrent_reviews = max_concurrent_reviews
        self._checkpointer = checkpointer
        self._graph = build_review_graph(
            self._reviewers,
            context_builder=context_builder,
            checkpointer=checkpointer,
        )

    async def run(
        self,
        request: PipelineRequest,
        *,
        cancellation: CancellationCheck | None = None,
        resume: bool = False,
    ) -> PipelineOutcome:
        """Прогоняет дифф, продолжая прерванный ход, если он сохранён.

        Продолжение отдаёт графу пустой вход: состояние он берёт из своего
        чекпоинта, и повторно переданные файлы затёрли бы уже прочитанное.
        Сохранённого хода может и не быть — прогон прервали до первого
        чекпоинта или сохранять его нечем, — и тогда продолжение честно идёт
        с начала. Пустой вход на пустой поток граф не принимает вовсе.
        """
        entry = (
            None
            if await self._has_saved_progress(request, resume=resume)
            else (ReviewGraphState(request=request))
        )

        try:
            raw = await self._graph.ainvoke(
                entry,
                context=ReviewRuntimeContext(
                    cancellation=cancellation,
                    navigator=self._navigator_for(request),
                    sink=self._sink_for(request),
                ),
                config=self._config(request),
            )
        except ReviewInterruptedError:
            return PipelineOutcome(is_cancelled=True)

        state = ReviewGraphState.model_validate(raw)
        read_paths = {item.file.path for item in state.results if item.degradation is None}
        review_failures = tuple(
            item.degradation for item in state.results if item.degradation is not None
        )

        return PipelineOutcome(
            findings=state.findings,
            usage=_total_usage(state.results),
            proposed=state.proposed,
            discarded_outside_diff=state.discarded_outside_diff,
            discarded_without_evidence=state.discarded_without_evidence,
            discarded_as_duplicate=state.discarded_as_duplicate,
            degradations=(*state.degradations, *review_failures),
            failed_files=_failure_reasons(review_failures),
            unreviewed_files=tuple(
                sorted(
                    {mark.file_path for mark in review_failures if mark.file_path not in read_paths}
                )
            ),
            files_with_context=state.files_with_context,
            reviewed_files=len(read_paths),
        )

    def _navigator_for(self, request: PipelineRequest) -> CodeNavigator | None:
        """Чем этот прогон будет ходить по коду.

        Навигатор рождается на прогон, а не на приложение: он привязан
        к репозиторию и ревизии. Его отсутствие — не сбой: агентный ревьюер
        честно уйдёт на проход без инструментов.
        """
        if self._navigators is None:
            return None
        return self._navigators.for_request(request)

    def _sink_for(self, request: PipelineRequest) -> InvestigationSink | None:
        """Куда этот прогон рассказывает о ходе расследования.

        Слушатель рождается на прогон: он подписывает шаги его именем,
        и без прогона запись некуда отнести.
        """
        if self._sinks is None:
            return None
        return self._sinks.for_run(request.run_id)

    async def forget(self, run_id: ReviewRunId) -> None:
        if self._checkpointer is None:
            return
        await self._checkpointer.adelete_thread(str(run_id))

    async def _has_saved_progress(self, request: PipelineRequest, *, resume: bool) -> bool:
        """Есть ли что продолжать.

        Спрашивать обязательно: до первого чекпоинта прогон успевает прожить
        минуты — столько собирается контекст, — и прекращённый в это время
        поток пуст. Пустой вход на пустом потоке граф отвергает
        `EmptyInputError`, и продолжение падает вместо того, чтобы просто
        начать сначала.
        """
        if not resume or self._checkpointer is None:
            return False
        return await self._checkpointer.aget_tuple(self._config(request)) is not None

    def _config(self, request: PipelineRequest) -> RunnableConfig:
        """Прогон опознаётся по своему идентификатору.

        Ветвление `Send` устроено так, что уже отработавшая пара «файл ×
        ревьюер» второй раз не запускается: продолжение дочитывает остаток,
        а не начинает сначала.
        """
        return {
            "max_concurrency": self._max_concurrent_reviews,
            "configurable": {"thread_id": str(request.run_id)},
        }


def _failure_reasons(marks: tuple[NodeDegradation, ...]) -> tuple[str, ...]:
    """Причины сбоев строками, по одной на каждую свою.

    Ревьюеров несколько, и упираются они в одно и то же: обрыв на лимите
    выхода настигает всех четверых на одном и том же большом файле. Четыре
    одинаковые строки в отчёте не добавляют к нему ничего, кроме длины.
    """
    seen: dict[str, None] = {}
    for mark in marks:
        seen.setdefault(f"{mark.file_path}: {mark.detail}", None)
    return tuple(seen)


def _total_usage(results: list[FileDrafts]) -> LlmUsage:
    total = LlmUsage()
    for item in results:
        total = LlmUsage(
            input_tokens=total.input_tokens + item.usage.input_tokens,
            output_tokens=total.output_tokens + item.usage.output_tokens,
            cost_usd=total.cost_usd + item.usage.cost_usd,
        )
    return total
