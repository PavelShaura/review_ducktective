from typing import (
    Any,
)

from langgraph.runtime import (
    Runtime,
)
from langgraph.types import (
    Send,
)

from ducktective.core.review.planning import (
    plan_file_review,
)
from ducktective.core.review.reviewers import (
    ReviewMode,
    review_mode_of,
)
from ducktective.review_graph.const import (
    AGGREGATE_NODE,
    REVIEW_NODE,
)
from ducktective.review_graph.nodes.reporting import (
    report_stage,
)
from ducktective.review_graph.ports import (
    RuntimeNode,
)
from ducktective.review_graph.state import (
    FileReviewTask,
    ReviewGraphState,
    ReviewRuntimeContext,
)


def plan_review_node(
    reviewer_names: tuple[str, ...],
) -> RuntimeNode:
    """Решает, как читать каждый файл — до того, как собрано окружение.

    Порядок именно такой: окружение нужно только тому файлу, который читается
    одним проходом. Агенту оно не собирается вовсе — он добывает нужное сам,
    и показанное заранее только отучает его спрашивать.

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

    async def plan_review(
        state: ReviewGraphState,
        *,
        runtime: Runtime[ReviewRuntimeContext],
    ) -> dict[str, Any]:
        tasks: list[FileReviewTask] = []
        for file in state.request.files:
            mode = plan_file_review(file, available=known.keys())
            planned = [known[mode]] if mode is not None else []
            planned.extend(unknown)
            tasks.extend(
                FileReviewTask(
                    file=file,
                    reviewer_name=name,
                    requirements=state.request.requirements,
                )
                for name in planned
            )
        await report_stage(runtime, _describe_plan(tasks))
        return {"tasks": tuple(tasks)}

    return plan_review


def _describe_plan(tasks: list[FileReviewTask]) -> str:
    """Что и чем будет прочитано.

    Названы оба числа: у режимов разная цена, и человек по этой строке
    заранее понимает, чего ждать от прогона.
    """
    agentic = sum(1 for task in tasks if review_mode_of(task.reviewer_name) is ReviewMode.AGENTIC)
    plain = len(tasks) - agentic
    if not tasks:
        return "Читать нечего: в диффе нет файлов для ревью"
    if not plain:
        return f"План: расследую {agentic} файл(ов) с инструментами"
    if not agentic:
        return f"План: читаю {plain} файл(ов) одним проходом"
    return f"План: {agentic} файл(ов) с инструментами, {plain} одним проходом"


def dispatch_reviews(state: ReviewGraphState) -> list[Send] | str:
    """Разводит запланированные пары «файл × ревьюер» по параллельным ветвям.

    Собранное окружение подставляется здесь, а не в плане: план строится
    раньше сборки, потому что от него зависит, какому файлу окружение вообще
    нужно.

    Пустой дифф не должен упираться в ветвление без исходящих рёбер, поэтому
    при отсутствии задач управление уходит сразу на слияние.
    """
    if not state.tasks:
        return AGGREGATE_NODE

    return [
        Send(REVIEW_NODE, task.model_copy(update={"context": state.contexts.get(task.file.path)}))
        for task in state.tasks
    ]
