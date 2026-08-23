from dataclasses import (
    dataclass,
)

from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.core.code_repository.value_objects import (
    ModelTrust,
)
from ducktective.core.exceptions import (
    SecretNotDecryptableError,
)
from ducktective.core.llm.provider_connection import (
    ProviderConnection,
    SecretCipher,
)
from ducktective.core.ports import (
    EventPublisher,
    UnitOfWork,
)
from ducktective.core.types import (
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class ResolvedModel:
    """Модель подключения с расшифрованным ключом, готовая к вызову.

    Живёт ровно столько, сколько собирается роутер: расшифрованный ключ
    не кладётся ни в ответ API, ни в журнал, ни в состояние прогона.
    """

    name: str
    model: str
    provider: str
    base_url: str
    api_key: str
    trust: ModelTrust
    supports_tools: bool
    context_window: int


class LoadTenantModels(TransactionalUseCase):
    """Модели организации для роутера — по одной на каждую модель подключения.

    Отдельно от чтения списка в интерфейс: там ключ не нужен и не должен
    покидать базу вовсе, здесь без него нельзя обратиться к провайдеру.

    Подключение, чей ключ не расшифровался сменившимся секретом, пропускается:
    отказ собрать роутер целиком оставил бы прогон без единой модели, включая
    локальную, которой секрет не нужен.
    """

    def __init__(
        self,
        unit_of_work: UnitOfWork,
        event_publisher: EventPublisher,
        cipher: SecretCipher | None,
    ) -> None:
        super().__init__(unit_of_work, event_publisher)
        self._cipher = cipher

    async def execute(self, tenant_id: TenantId) -> tuple[ResolvedModel, ...]:
        async with self._unit_of_work:
            connections = await self._unit_of_work.provider_connections.list_for_tenant(tenant_id)

        resolved: list[ResolvedModel] = []
        for connection in connections:
            if not connection.is_enabled:
                continue

            api_key = self._decrypt(connection)
            if api_key is None:
                continue

            resolved.extend(self._models_of(connection, api_key))

        return tuple(resolved)

    def _decrypt(self, connection: ProviderConnection) -> str | None:
        """`None` означает «это подключение сейчас непригодно»."""
        if not connection.encrypted_api_key:
            return ""
        if self._cipher is None:
            return None

        try:
            return self._cipher.decrypt(connection.encrypted_api_key)
        except SecretNotDecryptableError:
            return None

    @staticmethod
    def _models_of(connection: ProviderConnection, api_key: str) -> list[ResolvedModel]:
        return [
            ResolvedModel(
                name=connection.qualified(model),
                model=model,
                provider=connection.provider,
                base_url=connection.base_url,
                api_key=api_key,
                trust=connection.trust,
                supports_tools=connection.supports_tools,
                context_window=connection.context_window,
            )
            for model in connection.models
        ]
