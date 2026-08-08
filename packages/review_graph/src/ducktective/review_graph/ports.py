from typing import (
    Any,
    Protocol,
)

from langgraph.runtime import (
    Runtime,
)

from ducktective.review_graph.state import (
    FileReviewTask,
    ReviewGraphState,
    ReviewRuntimeContext,
)


class StateNode(Protocol):
    """Узел, читающий состояние прогона целиком.

    Объявлен здесь, а не взят у LangGraph: подходящий тип живёт в приватном
    модуле библиотеки и наружу не экспортируется. Форма совпадает структурно,
    поэтому узлы принимаются графом без приведений.
    """

    async def __call__(self, state: ReviewGraphState) -> dict[str, Any]: ...


class RuntimeNode(Protocol):
    """Узел, которому нужен контекст прогона, а не только состояние.

    Через контекст узел слышит просьбу прекратить и рассказывает ленте, чем
    занят. Отдельно от `StateNode`, потому что лишний параметр у узлов,
    которым он не нужен, пришлось бы объяснять.
    """

    async def __call__(
        self,
        state: ReviewGraphState,
        *,
        runtime: Runtime[ReviewRuntimeContext],
    ) -> dict[str, Any]: ...


class ReviewerNode(Protocol):
    """Узел одной ветви разветвления: свой вход вместо общего состояния."""

    async def __call__(
        self,
        state: FileReviewTask,
        *,
        runtime: Runtime[ReviewRuntimeContext],
    ) -> dict[str, Any]: ...
