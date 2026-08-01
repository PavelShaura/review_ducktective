from typing import (
    Any,
)

from langgraph.types import (
    Send,
)

from ducktective.review_graph.const import (
    AGGREGATE_NODE,
    REVIEW_NODE,
)
from ducktective.review_graph.ports import (
    StateNode,
)
from ducktective.review_graph.state import (
    FileReviewTask,
    ReviewGraphState,
)


def plan_review_node(
    reviewer_names: tuple[str, ...],
) -> StateNode:
    """Решает, кто и какой файл смотрит.

    Пока ревьюер один и получает все файлы. Здесь же появится выбор подмножества
    по языку, пути и содержимому файла: четыре прохода на каждый файл при
    локальной модели превращают прогон в многочасовой, и ограничивать стоимость
    больше негде.
    """

    async def plan_review(state: ReviewGraphState) -> dict[str, Any]:
        tasks = tuple(
            FileReviewTask(
                file=file,
                context=state.contexts.get(file.path),
                reviewer_name=name,
                requirements=state.request.requirements,
            )
            for file in state.request.files
            for name in reviewer_names
        )
        return {"tasks": tasks}

    return plan_review


def dispatch_reviews(state: ReviewGraphState) -> list[Send] | str:
    """Разводит запланированные пары «файл × ревьюер» по параллельным ветвям.

    Пустой дифф не должен упираться в ветвление без исходящих рёбер, поэтому
    при отсутствии задач управление уходит сразу на слияние.
    """
    if not state.tasks:
        return AGGREGATE_NODE
    return [Send(REVIEW_NODE, task) for task in state.tasks]
