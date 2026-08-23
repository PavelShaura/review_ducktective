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
from ducktective.core.llm.model_profile import (
    ModelProfile,
    ModelProfileId,
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


class ModelNameTakenError(ApplicationError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Модель с именем «{name}» уже заведена")
        self.name = name


class ModelNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__("Модель не найдена")


@dataclass(frozen=True, kw_only=True)
class AddModelCommand:
    actor_id: UserId
    name: str
    model: str
    api_key: str
    provider: str = ""
    base_url: str = ""
    trust: ModelTrust = ModelTrust.TRAINING_REMOTE
    supports_tools: bool = True
    context_window: int = 0
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class UpdateModelCommand:
    actor_id: UserId
    profile_id: ModelProfileId
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    trust: ModelTrust | None = None
    supports_tools: bool | None = None
    context_window: int | None = None
    note: str | None = None
    is_enabled: bool | None = None


class ListModelProfiles(TransactionalUseCase):
    """Модели организации. Ключи не покидают базу даже в шифрованном виде."""

    async def execute(self, actor_id: UserId) -> list[ModelProfile]:
        async with self._unit_of_work:
            actor = await self._unit_of_work.user_accounts.get(actor_id)
            return await self._unit_of_work.model_profiles.list_for_tenant(actor.tenant_id)


class AddModelProfile(TransactionalUseCase):
    """Заводит модель организации.

    Право — у владельца: список моделей решает, куда уедет код, ровно как
    политика egress репозитория, и правило для них одно (D-029).
    """

    def __init__(
        self,
        unit_of_work: UnitOfWork,
        event_publisher: EventPublisher,
        cipher: SecretCipher,
    ) -> None:
        super().__init__(unit_of_work, event_publisher)
        self._cipher = cipher

    async def execute(self, command: AddModelCommand) -> ModelProfile:
        async with self._unit_of_work:
            actor = await self._unit_of_work.user_accounts.get(command.actor_id)
            actor.ensure_manages_organization()

            taken = await self._unit_of_work.model_profiles.find_by_name(
                actor.tenant_id,
                command.name.strip(),
            )
            if taken is not None:
                raise ModelNameTakenError(command.name)

            profile = ModelProfile.create(
                tenant_id=actor.tenant_id,
                name=command.name,
                model=command.model,
                encrypted_api_key=(
                    self._cipher.encrypt(command.api_key) if command.api_key else ""
                ),
                provider=command.provider,
                base_url=command.base_url,
                trust=command.trust,
                supports_tools=command.supports_tools,
                context_window=command.context_window,
                note=command.note,
            )
            self._unit_of_work.model_profiles.add(profile)
            await self._commit_and_publish()

        return profile


class UpdateModelProfile(TransactionalUseCase):
    def __init__(
        self,
        unit_of_work: UnitOfWork,
        event_publisher: EventPublisher,
        cipher: SecretCipher,
    ) -> None:
        super().__init__(unit_of_work, event_publisher)
        self._cipher = cipher

    async def execute(self, command: UpdateModelCommand) -> ModelProfile:
        async with self._unit_of_work:
            actor = await self._unit_of_work.user_accounts.get(command.actor_id)
            actor.ensure_manages_organization()

            profile = await self._find(actor.tenant_id, command.profile_id)
            profile.update(
                model=command.model,
                base_url=command.base_url,
                trust=command.trust,
                supports_tools=command.supports_tools,
                context_window=command.context_window,
                note=command.note,
                is_enabled=command.is_enabled,
                encrypted_api_key=(
                    self._cipher.encrypt(command.api_key) if command.api_key else None
                ),
            )
            await self._commit_and_publish()

        return profile

    async def _find(self, tenant_id: TenantId, profile_id: ModelProfileId) -> ModelProfile:
        """Ищет среди своих же: чужая модель не отличается от несуществующей."""
        profiles = await self._unit_of_work.model_profiles.list_for_tenant(tenant_id)
        for profile in profiles:
            if profile.id == profile_id:
                return profile
        raise ModelNotFoundError


class DeleteModelProfile(TransactionalUseCase):
    async def execute(self, actor_id: UserId, profile_id: ModelProfileId) -> None:
        async with self._unit_of_work:
            actor = await self._unit_of_work.user_accounts.get(actor_id)
            actor.ensure_manages_organization()

            profiles = await self._unit_of_work.model_profiles.list_for_tenant(actor.tenant_id)
            target = next((profile for profile in profiles if profile.id == profile_id), None)
            if target is None:
                raise ModelNotFoundError

            await self._unit_of_work.model_profiles.remove(target)
            await self._commit_and_publish()
