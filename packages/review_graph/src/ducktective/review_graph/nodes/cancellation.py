from langgraph.runtime import (
    Runtime,
)

from ducktective.review_graph.state import (
    ReviewRuntimeContext,
)


async def is_cancelled(runtime: Runtime[ReviewRuntimeContext]) -> bool:
    """Сверяется с просьбой прекратить перед долгой работой.

    Спрашивают между файлами: и чтение файла моделью, и сборка его окружения
    занимают десятки секунд, а прерывать их на середине нечем и незачем.
    """
    context = runtime.context
    if context is None or context.cancellation is None:
        return False
    return await context.cancellation()
