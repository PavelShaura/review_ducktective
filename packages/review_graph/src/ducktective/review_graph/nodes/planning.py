from typing import (
    Any,
)

from langgraph.types import (
    Send,
)

from ducktective.core.review.planning import (
    select_reviewers,
)
from ducktective.core.review.reviewers import (
    reviewer_kind_of,
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

    Единственный узел, где принимается решение о стоимости прогона (D-018):
    четыре прохода на каждый файл при локальной модели превращают прогон
    на десять файлов в двухчасовой, а ревьюеры по построению независимы —
    ограничивать их число больше негде.

    Сам отбор — доменное правило, узел лишь переводит вид ревьюера в имя
    собранного. Ревьюер, за именем которого не стоит известной домену
    специализации, получает все файлы: политика о нём ничего не знает
    и потому его не сокращает.
    """
    specialised = {
        kind: name for name in reviewer_names if (kind := reviewer_kind_of(name)) is not None
    }
    unspecialised = tuple(name for name in reviewer_names if reviewer_kind_of(name) is None)

    async def plan_review(state: ReviewGraphState) -> dict[str, Any]:
        tasks: list[FileReviewTask] = []
        for file in state.request.files:
            context = state.contexts.get(file.path)
            selected = select_reviewers(file, context=context, available=specialised.keys())
            tasks.extend(
                FileReviewTask(
                    file=file,
                    context=context,
                    reviewer_name=name,
                    requirements=state.request.requirements,
                )
                for name in (*(specialised[kind] for kind in selected), *unspecialised)
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
