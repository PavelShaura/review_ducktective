from ducktective.core.retrieval.navigation import (
    CodeNavigator,
    CodeNavigatorFactory,
    GitNavigatorFactory,
)
from ducktective.core.review.pipeline import (
    PipelineRequest,
)


class RequestNavigators:
    """Выбирает, чем прогон будет ходить по коду.

    Обе реализации навигации приходят портами: граф не имеет права знать
    ни про базу, ни про запуск команд, а решение здесь принимается одно —
    какой из них подходит этому прогону.

    Индекс предпочитается всегда, когда он собран: разница между обходом
    графа и совпадением имени измерена и она в пользу графа. Без индекса
    берётся git по той же ревизии — вырождаться в проход без инструментов
    прогон не обязан (D-021).
    """

    def __init__(
        self,
        *,
        indexed: CodeNavigatorFactory | None = None,
        git: GitNavigatorFactory | None = None,
    ) -> None:
        self._indexed = indexed
        self._git = git

    def for_request(self, request: PipelineRequest) -> CodeNavigator | None:
        if request.index_ready and self._indexed is not None:
            return self._indexed.for_repository(request.repository_id)

        if self._git is not None and request.repository_path and request.head_sha:
            return self._git.for_revision(request.repository_path, request.head_sha)

        return None
