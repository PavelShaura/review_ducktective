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
from ducktective.core.tenancy.entities import (
    Invitation,
    Tenant,
    UserAccount,
)
from ducktective.core.tenancy.value_objects import (
    InvitationStatus,
)
from ducktective.core.types import (
    InvitationId,
    TenantId,
    UserId,
)
from ducktective.storage.mappers import tenancy as mapper
from ducktective.storage.models.tenancy import (
    TenantInvitationModel,
    TenantModel,
    UserAccountModel,
)


class SqlAlchemyTenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._identity_map: dict[TenantId, tuple[Tenant, TenantModel]] = {}

    def add(self, tenant: Tenant) -> None:
        model = mapper.tenant_to_model(tenant)
        self._session.add(model)
        self._identity_map[tenant.id] = (tenant, model)

    async def get(self, tenant_id: TenantId) -> Tenant:
        tracked = self._identity_map.get(tenant_id)
        if tracked is not None:
            return tracked[0]

        model = await self._session.get(TenantModel, tenant_id)
        if model is None:
            raise EntityNotFoundError("Tenant", tenant_id)
        return self._track(model)

    async def find_by_slug(self, slug: str) -> Tenant | None:
        statement = select(TenantModel).where(TenantModel.slug == slug)
        model = (await self._session.execute(statement)).scalar_one_or_none()
        if model is None:
            return None
        return self._track(model)

    def flush_changes(self) -> None:
        for tenant, model in self._identity_map.values():
            mapper.apply_tenant_changes(model, tenant)

    def collect_events(self) -> list[DomainEvent]:
        collected: list[DomainEvent] = []
        for tenant, _ in self._identity_map.values():
            collected.extend(tenant.pull_events())
        return collected

    def _track(self, model: TenantModel) -> Tenant:
        tenant_id = TenantId(model.id)
        tracked = self._identity_map.get(tenant_id)
        if tracked is not None:
            return tracked[0]

        tenant = mapper.tenant_to_domain(model)
        self._identity_map[tenant_id] = (tenant, model)
        return tenant


class SqlAlchemyUserAccountRepository:
    """Репозиторий участников организации.

    Поиск по личности идёт без фильтра по тенанту сознательно: на этом шаге
    тенант ещё не известен — он и выясняется из найденного членства.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._identity_map: dict[UserId, tuple[UserAccount, UserAccountModel]] = {}
        self._removed_events: list[DomainEvent] = []

    def add(self, account: UserAccount) -> None:
        model = mapper.account_to_model(account)
        self._session.add(model)
        self._identity_map[account.id] = (account, model)

    async def get(self, user_id: UserId) -> UserAccount:
        tracked = self._identity_map.get(user_id)
        if tracked is not None:
            return tracked[0]

        model = await self._session.get(UserAccountModel, user_id)
        if model is None:
            raise EntityNotFoundError("UserAccount", user_id)
        return self._track(model)

    async def find_by_identity(self, *, issuer: str, subject: str) -> UserAccount | None:
        statement = select(UserAccountModel).where(
            UserAccountModel.external_issuer == issuer,
            UserAccountModel.external_subject == subject,
        )
        model = (await self._session.execute(statement)).scalar_one_or_none()
        if model is None:
            return None
        return self._track(model)

    async def list_for_tenant(self, tenant_id: TenantId) -> list[UserAccount]:
        statement = (
            select(UserAccountModel)
            .where(UserAccountModel.tenant_id == tenant_id)
            .order_by(UserAccountModel.created_at)
        )
        models = (await self._session.execute(statement)).scalars().all()
        return [self._track(model) for model in models]

    async def remove(self, account: UserAccount) -> None:
        tracked = self._identity_map.pop(account.id, None)
        model = (
            tracked[1]
            if tracked is not None
            else await self._session.get(UserAccountModel, account.id)
        )
        if model is None:
            raise EntityNotFoundError("UserAccount", account.id)

        await self._session.delete(model)
        self._removed_events.extend(account.pull_events())

    def flush_changes(self) -> None:
        for account, model in self._identity_map.values():
            mapper.apply_account_changes(model, account)

    def collect_events(self) -> list[DomainEvent]:
        collected = self._removed_events
        self._removed_events = []
        for account, _ in self._identity_map.values():
            collected.extend(account.pull_events())
        return collected

    def _track(self, model: UserAccountModel) -> UserAccount:
        user_id = UserId(model.id)
        tracked = self._identity_map.get(user_id)
        if tracked is not None:
            return tracked[0]

        account = mapper.account_to_domain(model)
        self._identity_map[user_id] = (account, model)
        return account


class SqlAlchemyInvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._identity_map: dict[InvitationId, tuple[Invitation, TenantInvitationModel]] = {}

    def add(self, invitation: Invitation) -> None:
        model = mapper.invitation_to_model(invitation)
        self._session.add(model)
        self._identity_map[invitation.id] = (invitation, model)

    async def get(self, invitation_id: InvitationId) -> Invitation:
        tracked = self._identity_map.get(invitation_id)
        if tracked is not None:
            return tracked[0]

        model = await self._session.get(TenantInvitationModel, invitation_id)
        if model is None:
            raise EntityNotFoundError("Invitation", invitation_id)
        return self._track(model)

    async def find_by_token_digest(self, digest: str) -> Invitation | None:
        statement = select(TenantInvitationModel).where(
            TenantInvitationModel.token_digest == digest
        )
        model = (await self._session.execute(statement)).scalar_one_or_none()
        if model is None:
            return None
        return self._track(model)

    async def list_pending(self, tenant_id: TenantId) -> list[Invitation]:
        statement = (
            select(TenantInvitationModel)
            .where(
                TenantInvitationModel.tenant_id == tenant_id,
                TenantInvitationModel.status == InvitationStatus.PENDING,
            )
            .order_by(TenantInvitationModel.created_at.desc())
        )
        models = (await self._session.execute(statement)).scalars().all()
        return [self._track(model) for model in models]

    def flush_changes(self) -> None:
        for invitation, model in self._identity_map.values():
            mapper.apply_invitation_changes(model, invitation)

    def collect_events(self) -> list[DomainEvent]:
        collected: list[DomainEvent] = []
        for invitation, _ in self._identity_map.values():
            collected.extend(invitation.pull_events())
        return collected

    def _track(self, model: TenantInvitationModel) -> Invitation:
        invitation_id = InvitationId(model.id)
        tracked = self._identity_map.get(invitation_id)
        if tracked is not None:
            return tracked[0]

        invitation = mapper.invitation_to_domain(model)
        self._identity_map[invitation_id] = (invitation, model)
        return invitation
