from dataclasses import (
    dataclass,
)

from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    ApplicationError,
)
from ducktective.core.tenancy.entities import (
    Tenant,
    UserAccount,
)
from ducktective.core.tenancy.value_objects import (
    TenantRole,
    VerifiedIdentity,
)


@dataclass(frozen=True, kw_only=True)
class CreateOrganizationCommand:
    identity: VerifiedIdentity
    slug: str
    name: str


@dataclass(frozen=True, kw_only=True)
class CreatedOrganization:
    tenant: Tenant
    owner: UserAccount


class OrganizationSlugTakenError(ApplicationError):
    def __init__(self, slug: str) -> None:
        super().__init__(f"Короткое имя «{slug}» уже занято")
        self.slug = slug


class AlreadyInOrganizationError(ApplicationError):
    """Вошедший уже состоит в организации.

    Первая версия держит одну организацию на личность (D-027): иначе вместе
    с членствами появляется выбор активного, а он пронизывает и токен,
    и каждый запрос.
    """

    def __init__(self) -> None:
        super().__init__("Учётная запись уже состоит в организации")


class CreateOrganization(TransactionalUseCase):
    """Создание организации тем, кто вошёл, но никуда не принят.

    Создатель становится владельцем в той же транзакции: организация без
    владельца нарушила бы инвариант с первой же секунды существования.
    """

    async def execute(self, command: CreateOrganizationCommand) -> CreatedOrganization:
        async with self._unit_of_work:
            existing_membership = await self._unit_of_work.user_accounts.find_by_identity(
                issuer=command.identity.issuer,
                subject=command.identity.subject,
            )
            if existing_membership is not None:
                raise AlreadyInOrganizationError

            slug = command.slug.strip().lower()
            if await self._unit_of_work.tenants.find_by_slug(slug) is not None:
                raise OrganizationSlugTakenError(slug)

            tenant = Tenant.create(slug=slug, name=command.name)
            owner = UserAccount.provision(
                tenant_id=tenant.id,
                identity=command.identity,
                role=TenantRole.OWNER,
            )
            self._unit_of_work.tenants.add(tenant)
            self._unit_of_work.user_accounts.add(owner)
            await self._commit_and_publish()

        return CreatedOrganization(tenant=tenant, owner=owner)
