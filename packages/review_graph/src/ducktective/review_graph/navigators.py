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

    Индекс предпочитается, когда собран **на той же ревизии**, которую ревьюим:
    разница между обходом графа и совпадением имени измерена и она в пользу
    графа. Индекс с другого коммита — хуже, чем никакого: изменённых символов
    в нём нет, `find_callers` отвечает пустотой, и модель принимает её за
    «вызывающих не существует». Ровно так 2026-08-08 родились две ложные
    находки из четырёх.

    Поэтому при расхождении ревизий берётся git по нужному коммиту: он грубее
    графа, зато отвечает про тот код, который ревьюят.
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
        if request.index_matches_revision and self._indexed is not None:
            return self._indexed.for_repository(request.repository_id)

        if self._git is not None and request.repository_path and request.head_sha:
            return self._git.for_revision(
                request.repository_path,
                request.head_sha,
                reason=_why_not_index(request),
            )

        if request.index_revision is not None and self._indexed is not None:
            return self._indexed.for_repository(request.repository_id)

        return None


def _why_not_index(request: PipelineRequest) -> str:
    """Почему отвечает git, а не индекс.

    Разница важна модели: «индекса нет» означает, что структурных связей
    взять неоткуда, а «индекс на другом коммите» — что они есть, просто
    отсюда не видны, и пустой ответ поиска ничего не доказывает.
    """
    if request.index_revision is None:
        return "индекса нет"
    return f"индекс собран на другой ревизии ({request.index_revision[:8]})"
