from dataclasses import (
    dataclass,
)

from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    ApplicationError,
)
from ducktective.core.code_repository.value_objects import (
    ModelTrust,
)
from ducktective.core.llm.provider_connection import (
    ConnectionId,
    ProviderConnection,
    SecretCipher,
)
from ducktective.core.ports import (
    EventPublisher,
    UnitOfWork,
)
from ducktective.core.types import (
    TenantId,
    UserId,
)


class ConnectionNameTakenError(ApplicationError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Подключение с именем «{name}» уже заведено")
        self.name = name


class ConnectionNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__("Подключение не найдено")


@dataclass(frozen=True, kw_only=True)
class AddConnectionCommand:
    actor_id: UserId
    name: str
    api_key: str = ""
    default_model: str = ""
    catalogue: tuple[str, ...] = ()
    provider: str = ""
    base_url: str = ""
    trust: ModelTrust = ModelTrust.TRAINING_REMOTE
    supports_tools: bool = True
    context_window: int = 0
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class UpdateConnectionCommand:
    actor_id: UserId
    connection_id: ConnectionId
    default_model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    trust: ModelTrust | None = None
    supports_tools: bool | None = None
    context_window: int | None = None
    note: str | None = None
    is_enabled: bool | None = None
    catalogue: tuple[str, ...] | None = None


class ListProviderConnections(TransactionalUseCase):
    """Подключения организации. Ключи не покидают базу даже шифротекстом."""

    async def execute(self, actor_id: UserId) -> list[ProviderConnection]:
        async with self._unit_of_work:
            actor = await self._unit_of_work.user_accounts.get(actor_id)
            return await self._unit_of_work.provider_connections.list_for_tenant(actor.tenant_id)


class ConnectionUseCase(TransactionalUseCase):
    """Общее для правок состава подключений: право и поиск среди своих.

    Право — у владельца: список подключений решает, куда уедет код, ровно
    как политика egress репозитория, и правило для них одно (D-029).
    """

    def __init__(
        self,
        unit_of_work: UnitOfWork,
        event_publisher: EventPublisher,
        cipher: SecretCipher | None = None,
    ) -> None:
        super().__init__(unit_of_work, event_publisher)
        self._cipher = cipher

    async def _find(self, tenant_id: TenantId, connection_id: ConnectionId) -> ProviderConnection:
        """Ищет среди своих же: чужое подключение неотличимо от несуществующего."""
        connections = await self._unit_of_work.provider_connections.list_for_tenant(tenant_id)
        for connection in connections:
            if connection.id == connection_id:
                return connection
        raise ConnectionNotFoundError

    def _encrypt(self, api_key: str) -> str:
        if not api_key:
            return ""
        if self._cipher is None:
            raise ApplicationError("Ключ негде зашифровать: не задан секрет MODELS_SECRET_KEY")
        return self._cipher.encrypt(api_key)


class AddProviderConnection(ConnectionUseCase):
    async def execute(self, command: AddConnectionCommand) -> ProviderConnection:
        async with self._unit_of_work:
            actor = await self._unit_of_work.user_accounts.get(command.actor_id)
            actor.ensure_manages_organization()

            taken = await self._unit_of_work.provider_connections.find_by_name(
                actor.tenant_id,
                command.name.strip(),
            )
            if taken is not None:
                raise ConnectionNameTakenError(command.name)

            connection = ProviderConnection.create(
                tenant_id=actor.tenant_id,
                name=command.name,
                encrypted_api_key=self._encrypt(command.api_key),
                default_model=command.default_model,
                catalogue=list(command.catalogue),
                provider=command.provider,
                base_url=command.base_url,
                trust=command.trust,
                supports_tools=command.supports_tools,
                context_window=command.context_window,
                note=command.note,
            )
            self._unit_of_work.provider_connections.add(connection)
            await self._commit_and_publish()

        return connection


class UpdateProviderConnection(ConnectionUseCase):
    async def execute(self, command: UpdateConnectionCommand) -> ProviderConnection:
        async with self._unit_of_work:
            actor = await self._unit_of_work.user_accounts.get(command.actor_id)
            actor.ensure_manages_organization()

            connection = await self._find(actor.tenant_id, command.connection_id)
            connection.update(
                default_model=command.default_model,
                base_url=command.base_url,
                trust=command.trust,
                supports_tools=command.supports_tools,
                context_window=command.context_window,
                note=command.note,
                is_enabled=command.is_enabled,
                encrypted_api_key=(self._encrypt(command.api_key) if command.api_key else None),
            )
            if command.catalogue is not None:
                connection.refresh_catalogue(list(command.catalogue))
            await self._commit_and_publish()

        return connection


class DeleteProviderConnection(ConnectionUseCase):
    async def execute(self, actor_id: UserId, connection_id: ConnectionId) -> None:
        async with self._unit_of_work:
            actor = await self._unit_of_work.user_accounts.get(actor_id)
            actor.ensure_manages_organization()

            connection = await self._find(actor.tenant_id, connection_id)
            await self._unit_of_work.provider_connections.remove(connection)
            await self._commit_and_publish()
