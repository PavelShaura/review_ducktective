from typing import (
    Any,
)

from langgraph.types import (
    Send,
)

from ducktective.core.review.planning import (
    plan_file_review,
)
from ducktective.core.review.reviewers import (
    review_mode_of,
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
    """Решает, как читать каждый файл.

    Единственный узел, где принимается решение о стоимости прогона (D-018).
    Ревьюер теперь один (D-022), поэтому узел выбирает не кого позвать,
    а каким способом читать: агентно, с дозапросом окружения, либо одним
    проходом по тому, что собрано заранее.

    Сам выбор — доменное правило, узел лишь переводит режим в имя собранного
    ревьюера. Ревьюер, за именем которого домен режима не знает, получает
    все файлы: политика о нём ничего не знает и потому его не сокращает.
    """
    known = {mode: name for name in reviewer_names if (mode := review_mode_of(name)) is not None}
    unknown = tuple(name for name in reviewer_names if review_mode_of(name) is None)

    async def plan_review(state: ReviewGraphState) -> dict[str, Any]:
        tasks: list[FileReviewTask] = []
        for file in state.request.files:
            context = state.contexts.get(file.path)
            mode = plan_file_review(file, available=known.keys())
            planned = [known[mode]] if mode is not None else []
            planned.extend(unknown)
            tasks.extend(
                FileReviewTask(
                    file=file,
                    context=context,
                    reviewer_name=name,
                    requirements=state.request.requirements,
                )
                for name in planned
            )
        return {"tasks": tuple(tasks)}

    return plan_review


def dispatch_reviews(state: ReviewGraphState) -> list[Send] | str:
    """Разводит запланированные пары «файл × ревьюер» по параллельным ветвям.

    Пустой дифф не должен упираться в ветвление без исходящих рёбер, поэтому
    при отсутствии задач управление уходит сразу на слияние.
    """
    if not state.tasks:
        return AGGREGATE_NODE
    return [Send(REVIEW_NODE, task) for task in state.tasks]
