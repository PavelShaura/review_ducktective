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
from ducktective.core.llm.model_profile import (
    ModelProfile,
    ModelProfileId,
)
from ducktective.core.types import (
    TenantId,
)
from ducktective.storage.mappers import model_profile as mapper
from ducktective.storage.models.model_profile import (
    ModelProfileModel,
)


class SqlAlchemyModelProfileRepository:
    """Модели организации. Ключи отдаются шифротекстом — расшифровка не здесь."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._identity_map: dict[ModelProfileId, tuple[ModelProfile, ModelProfileModel]] = {}

    def add(self, profile: ModelProfile) -> None:
        model = mapper.to_model(profile)
        self._session.add(model)
        self._identity_map[profile.id] = (profile, model)

    async def get(self, profile_id: ModelProfileId) -> ModelProfile:
        tracked = self._identity_map.get(profile_id)
        if tracked is not None:
            return tracked[0]

        model = await self._session.get(ModelProfileModel, profile_id)
        if model is None:
            raise EntityNotFoundError("ModelProfile", profile_id)
        return self._track(model)

    async def list_for_tenant(self, tenant_id: TenantId) -> list[ModelProfile]:
        statement = (
            select(ModelProfileModel)
            .where(ModelProfileModel.tenant_id == tenant_id)
            .order_by(ModelProfileModel.created_at)
        )
        models = (await self._session.execute(statement)).scalars().all()
        return [self._track(model) for model in models]

    async def find_by_name(self, tenant_id: TenantId, name: str) -> ModelProfile | None:
        statement = select(ModelProfileModel).where(
            ModelProfileModel.tenant_id == tenant_id,
            ModelProfileModel.name == name,
        )
        model = (await self._session.execute(statement)).scalar_one_or_none()
        if model is None:
            return None
        return self._track(model)

    async def remove(self, profile: ModelProfile) -> None:
        tracked = self._identity_map.pop(profile.id, None)
        model = (
            tracked[1]
            if tracked is not None
            else await self._session.get(ModelProfileModel, profile.id)
        )
        if model is None:
            raise EntityNotFoundError("ModelProfile", profile.id)
        await self._session.delete(model)

    def flush_changes(self) -> None:
        for profile, model in self._identity_map.values():
            mapper.apply_changes(model, profile)

    def collect_events(self) -> list[DomainEvent]:
        collected: list[DomainEvent] = []
        for profile, _ in self._identity_map.values():
            collected.extend(profile.pull_events())
        return collected

    def _track(self, model: ModelProfileModel) -> ModelProfile:
        tracked = self._identity_map.get(model.id)
        if tracked is not None:
            return tracked[0]

        profile = mapper.to_domain(model)
        self._identity_map[model.id] = (profile, model)
        return profile
