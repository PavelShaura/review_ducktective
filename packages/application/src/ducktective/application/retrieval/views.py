from dataclasses import (
    dataclass,
)

from ducktective.application.indexing.views import (
    IndexStateView,
)
from ducktective.core.types import (
    RepositoryId,
)


@dataclass(frozen=True, kw_only=True)
class RepositoryOverview:
    """Репозиторий вместе с состоянием его индекса.

    Одно без другого бесполезно: зарегистрированный репозиторий без индекса
    на вопросы не отвечает, и знать об этом нужно до того, как задан вопрос.
    """

    repository_id: RepositoryId
    name: str
    index: IndexStateView
