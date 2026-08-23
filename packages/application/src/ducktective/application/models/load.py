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
from ducktective.core.llm.model_profile import (
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
    """Модель организации с расшифрованным ключом, готовая к вызову.

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
    """Модели организации для роутера.

    Отдельно от чтения списка в интерфейс: там ключ не нужен и не должен
    покидать базу вовсе, здесь без него нельзя обратиться к провайдеру.

    Модель, чей ключ не расшифровался сменившимся секретом, пропускается:
    отказ собрать роутер целиком оставил бы прогон без единой модели,
    включая локальную, которой секрет не нужен.
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
            profiles = await self._unit_of_work.model_profiles.list_for_tenant(tenant_id)

        resolved: list[ResolvedModel] = []
        for profile in profiles:
            if not profile.is_enabled:
                continue

            api_key = ""
            if profile.encrypted_api_key:
                if self._cipher is None:
                    continue
                try:
                    api_key = self._cipher.decrypt(profile.encrypted_api_key)
                except SecretNotDecryptableError:
                    continue

            resolved.append(
                ResolvedModel(
                    name=profile.name,
                    model=profile.model,
                    provider=profile.provider,
                    base_url=profile.base_url,
                    api_key=api_key,
                    trust=profile.trust,
                    supports_tools=profile.supports_tools,
                    context_window=profile.context_window,
                )
            )

        return tuple(resolved)
