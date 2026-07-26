from sqlalchemy import (
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
)
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.types import (
    RepositoryId,
    ReviewRunId,
)
from ducktective.storage.mappers import review as mapper
from ducktective.storage.models.review import (
    ReviewRunModel,
)


class SqlAlchemyReviewRunRepository:
    """Репозиторий агрегата ReviewRun."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._identity_map: dict[ReviewRunId, tuple[ReviewRun, ReviewRunModel]] = {}

    def add(self, run: ReviewRun) -> None:
        model = mapper.to_model(run)
        self._session.add(model)
        self._identity_map[run.id] = (run, model)

    async def get(self, run_id: ReviewRunId) -> ReviewRun:
        tracked = self._identity_map.get(run_id)
        if tracked is not None:
            return tracked[0]

        model = await self._session.get(ReviewRunModel, run_id)
        if model is None:
            raise EntityNotFoundError("ReviewRun", run_id)
        return self._track(model)

    async def list_for_repository(
        self,
        repository_id: RepositoryId,
        *,
        limit: int = 50,
    ) -> list[ReviewRun]:
        statement = (
            select(ReviewRunModel)
            .where(ReviewRunModel.repository_id == repository_id)
            .order_by(ReviewRunModel.created_at.desc())
            .limit(limit)
        )
        models = (await self._session.execute(statement)).scalars().all()
        return [self._track(model) for model in models]

    def flush_changes(self) -> None:
        for run, model in self._identity_map.values():
            mapper.apply_changes(model, run)

    def collect_events(self) -> list[DomainEvent]:
        collected: list[DomainEvent] = []
        for run, _ in self._identity_map.values():
            collected.extend(run.pull_events())
        return collected

    def _track(self, model: ReviewRunModel) -> ReviewRun:
        run_id = ReviewRunId(model.id)
        tracked = self._identity_map.get(run_id)
        if tracked is not None:
            return tracked[0]

        run = mapper.to_domain(model)
        self._identity_map[run_id] = (run, model)
        return run
