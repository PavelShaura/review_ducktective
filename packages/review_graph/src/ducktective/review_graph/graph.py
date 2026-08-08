from collections.abc import (
    Mapping,
)
from typing import (
    Any,
)

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
)
from langgraph.graph import (
    END,
    START,
    StateGraph,
)
from langgraph.graph.state import (
    CompiledStateGraph,
)

from ducktective.core.retrieval.ports import (
    ContextBuilder,
)
from ducktective.core.review.ports import (
    CodeReviewer,
)
from ducktective.review_graph.const import (
    AGGREGATE_NODE,
    BUILD_CONTEXT_NODE,
    PLAN_REVIEW_NODE,
    REVIEW_NODE,
    VERIFY_NODE,
)
from ducktective.review_graph.nodes.aggregation import (
    aggregate,
)
from ducktective.review_graph.nodes.context import (
    build_context_node,
)
from ducktective.review_graph.nodes.planning import (
    dispatch_reviews,
    plan_review_node,
)
from ducktective.review_graph.nodes.reviewing import (
    review_node,
)
from ducktective.review_graph.nodes.verification import (
    verify,
)
from ducktective.review_graph.state import (
    FileReviewTask,
    ReviewGraphState,
    ReviewRuntimeContext,
)


ReviewGraph = CompiledStateGraph[
    ReviewGraphState,
    ReviewRuntimeContext,
    ReviewGraphState,
    ReviewGraphState,
]


def build_review_graph(
    reviewers: Mapping[str, CodeReviewer],
    *,
    context_builder: ContextBuilder | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> ReviewGraph:
    """Собирает конвейер из `05-review-pipeline.md`.

    План идёт перед сборкой окружения, а не после: окружение нужно только
    тому файлу, который читается одним проходом. Агент добывает его сам, и
    показать ему всё заранее значит лишить смысла его инструменты — на живом
    прогоне он звал их 5 раз на 17 файлов именно поэтому.

    Разбор диффа и привязка ханков к символам сюда не входят: первое делает
    `PrepareReviewRun` до постановки в очередь, второе — сборщик контекста.
    Узел оформления вывода появится вместе с применением патчей — пустых
    узлов в графе нет.
    """
    builder: StateGraph[ReviewGraphState, ReviewRuntimeContext, ReviewGraphState, ReviewGraphState]
    builder = StateGraph(ReviewGraphState, context_schema=ReviewRuntimeContext)

    builder.add_node(BUILD_CONTEXT_NODE, build_context_node(context_builder))
    builder.add_node(PLAN_REVIEW_NODE, plan_review_node(tuple(reviewers)))
    builder.add_node(REVIEW_NODE, review_node(reviewers), input_schema=FileReviewTask)
    builder.add_node(AGGREGATE_NODE, aggregate)
    builder.add_node(VERIFY_NODE, verify)

    builder.add_edge(START, PLAN_REVIEW_NODE)
    builder.add_edge(PLAN_REVIEW_NODE, BUILD_CONTEXT_NODE)
    builder.add_conditional_edges(
        BUILD_CONTEXT_NODE,
        dispatch_reviews,
        [REVIEW_NODE, AGGREGATE_NODE],
    )
    builder.add_edge(REVIEW_NODE, AGGREGATE_NODE)
    builder.add_edge(AGGREGATE_NODE, VERIFY_NODE)
    builder.add_edge(VERIFY_NODE, END)

    return builder.compile(checkpointer=checkpointer)
