from typing import (
    Annotated,
)

from fastapi import (
    Depends,
    Request,
)

from ducktective.storage.events.redis_publisher import (
    RedisEventPublisher,
)
from ducktective.storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
)


def get_unit_of_work(request: Request) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(request.app.state.session_factory)


def get_event_publisher(request: Request) -> RedisEventPublisher:
    return RedisEventPublisher(request.app.state.redis)


UnitOfWorkDependency = Annotated[SqlAlchemyUnitOfWork, Depends(get_unit_of_work)]
EventPublisherDependency = Annotated[RedisEventPublisher, Depends(get_event_publisher)]
