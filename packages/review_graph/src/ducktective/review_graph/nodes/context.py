from typing import (
    Any,
)

from ducktective.core.exceptions import (
    DomainError,
)
from ducktective.core.retrieval.context import (
    DiffContext,
)
from ducktective.core.retrieval.ports import (
    ContextBuilder,
)
from ducktective.core.review.degradation import (
    DegradationKind,
    NodeDegradation,
    ReviewStage,
)
from ducktective.core.review.entities import (
    ReviewFile,
)
from ducktective.core.types import (
    RepositoryId,
)
from ducktective.review_graph.ports import (
    StateNode,
)
from ducktective.review_graph.state import (
    ReviewGraphState,
)


def build_context_node(
    context_builder: ContextBuilder | None,
) -> StateNode:
    """Собирает окружение изменений для каждого файла диффа.

    Отсутствие или поломка индекса не отменяют ревью: оно продолжается по одному
    диффу, а число файлов с контекстом попадает в итог прогона, чтобы разницу
    в качестве не приходилось угадывать.
    """

    async def build_context(state: ReviewGraphState) -> dict[str, Any]:
        contexts: dict[str, DiffContext] = {}
        degradations: list[NodeDegradation] = []
        files_with_context = 0

        for file in state.request.files:
            context, failure = await _safely_build(
                context_builder,
                state.request.repository_id,
                file,
            )
            if failure is not None:
                degradations.append(failure)
            if context is None:
                continue

            contexts[file.path] = context
            if not context.is_empty:
                files_with_context += 1

        return {
            "contexts": contexts,
            "files_with_context": files_with_context,
            "degradations": degradations,
        }

    return build_context


async def _safely_build(
    context_builder: ContextBuilder | None,
    repository_id: RepositoryId,
    file: ReviewFile,
) -> tuple[DiffContext | None, NodeDegradation | None]:
    """Собирает окружение файла, обращая поломку индекса в отметку.

    Отсутствие сборщика отметки не порождает: ревью без индекса — это
    заявленный режим работы, а не деградация, и число файлов с контекстом
    уже говорит о нём честно.
    """
    if context_builder is None:
        return None, None

    try:
        return await context_builder.build(repository_id, file), None
    except DomainError as error:
        return None, NodeDegradation(
            stage=ReviewStage.BUILD_CONTEXT,
            file_path=file.path,
            kind=DegradationKind.CONTEXT_UNAVAILABLE,
            detail=str(error),
        )
