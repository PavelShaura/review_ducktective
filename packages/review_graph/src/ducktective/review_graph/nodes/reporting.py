from langgraph.runtime import (
    Runtime,
)

from ducktective.core.review.investigation import (
    InvestigationStep,
    StepKind,
)
from ducktective.review_graph.state import (
    ReviewRuntimeContext,
)


async def report_stage(
    runtime: Runtime[ReviewRuntimeContext],
    detail: str,
    *,
    file_path: str = "",
    number: int = 0,
) -> None:
    """Рассказывает ленте, чем прогон занят прямо сейчас.

    Зовётся из узлов, а не из ревьюера: до первого обращения к модели проходят
    минуты — столько собирается окружение на большом диффе, — и всё это время
    лента иначе пуста. Человек в ней смотрит не на шаги агента, а на ответ
    на вопрос «работа идёт или встала».

    Молчание слушателя не ошибка: в автономном прогоне его нет вовсе.
    """
    sink = runtime.context.sink
    if sink is None:
        return

    await sink.record(
        InvestigationStep(
            file_path=file_path,
            number=number,
            kind=StepKind.STAGE,
            detail=detail,
        )
    )
