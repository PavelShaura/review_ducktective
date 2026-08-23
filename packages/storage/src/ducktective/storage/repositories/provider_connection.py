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
from ducktective.core.llm.provider_connection import (
    ConnectionId,
    ProviderConnection,
)
from ducktective.core.types import (
    TenantId,
)
from ducktective.storage.mappers import provider_connection as mapper
from ducktective.storage.models.provider_connection import (
    ProviderConnectionModel,
)


class SqlAlchemyProviderConnectionRepository:
    """Подключения организации. Ключи отдаются шифротекстом — расшифровка не здесь."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._identity_map: dict[
            ConnectionId, tuple[ProviderConnection, ProviderConnectionModel]
        ] = {}

    def add(self, connection: ProviderConnection) -> None:
        model = mapper.to_model(connection)
        self._session.add(model)
        self._identity_map[connection.id] = (connection, model)

    async def get(self, connection_id: ConnectionId) -> ProviderConnection:
        tracked = self._identity_map.get(connection_id)
        if tracked is not None:
            return tracked[0]

        model = await self._session.get(ProviderConnectionModel, connection_id)
        if model is None:
            raise EntityNotFoundError("ProviderConnection", connection_id)
        return self._track(model)

    async def list_for_tenant(self, tenant_id: TenantId) -> list[ProviderConnection]:
        statement = (
            select(ProviderConnectionModel)
            .where(ProviderConnectionModel.tenant_id == tenant_id)
            .order_by(ProviderConnectionModel.created_at)
        )
        models = (await self._session.execute(statement)).scalars().all()
        return [self._track(model) for model in models]

    async def find_by_name(self, tenant_id: TenantId, name: str) -> ProviderConnection | None:
        statement = select(ProviderConnectionModel).where(
            ProviderConnectionModel.tenant_id == tenant_id,
            ProviderConnectionModel.name == name,
        )
        model = (await self._session.execute(statement)).scalar_one_or_none()
        if model is None:
            return None
        return self._track(model)

    async def remove(self, connection: ProviderConnection) -> None:
        tracked = self._identity_map.pop(connection.id, None)
        model = (
            tracked[1]
            if tracked is not None
            else await self._session.get(ProviderConnectionModel, connection.id)
        )
        if model is None:
            raise EntityNotFoundError("ProviderConnection", connection.id)
        await self._session.delete(model)

    def flush_changes(self) -> None:
        for connection, model in self._identity_map.values():
            mapper.apply_changes(model, connection)

    def collect_events(self) -> list[DomainEvent]:
        collected: list[DomainEvent] = []
        for connection, _ in self._identity_map.values():
            collected.extend(connection.pull_events())
        return collected

    def _track(self, model: ProviderConnectionModel) -> ProviderConnection:
        tracked = self._identity_map.get(model.id)
        if tracked is not None:
            return tracked[0]

        connection = mapper.to_domain(model)
        self._identity_map[model.id] = (connection, model)
        return connection
