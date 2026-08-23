from typing import (
    Protocol,
)

from ducktective.core.tenancy.entities import (
    Invitation,
    Tenant,
    UserAccount,
)
from ducktective.core.tenancy.value_objects import (
    VerifiedIdentity,
)
from ducktective.core.types import (
    InvitationId,
    TenantId,
    UserId,
)


class TenantRepository(Protocol):
    def add(self, tenant: Tenant) -> None: ...

    async def get(self, tenant_id: TenantId) -> Tenant: ...

    async def find_by_slug(self, slug: str) -> Tenant | None: ...


class UserAccountRepository(Protocol):
    def add(self, account: UserAccount) -> None: ...

    async def get(self, user_id: UserId) -> UserAccount: ...

    async def find_by_identity(self, *, issuer: str, subject: str) -> UserAccount | None:
        """Учётная запись по паре «издатель и субъект», без привязки к тенанту.

        Именно здесь выясняется, состоит ли вошедший хоть где-нибудь: тенант
        на этом шаге ещё неизвестен, поэтому фильтра по нему тут нет и быть
        не может.
        """
        ...

    async def list_for_tenant(self, tenant_id: TenantId) -> list[UserAccount]: ...

    async def remove(self, account: UserAccount) -> None: ...


class InvitationRepository(Protocol):
    def add(self, invitation: Invitation) -> None: ...

    async def get(self, invitation_id: InvitationId) -> Invitation: ...

    async def find_by_token_digest(self, digest: str) -> Invitation | None:
        """Приглашение по отпечатку секрета из ссылки.

        Тенанта в запросе нет по той же причине, что и у поиска по личности:
        принимающий приглашение ещё не принадлежит организации, в которую
        его зовут.
        """
        ...

    async def list_pending(self, tenant_id: TenantId) -> list[Invitation]: ...


class IdentityVerifier(Protocol):
    """Проверка предъявленного токена доступа.

    Порт объявлен доменом, потому что доменное правило «tenant_id берётся из
    членства вошедшего, а не из запроса» опирается на его результат. Чем
    именно подтверждена личность — подписью OIDC-провайдера или чем-то
    иным, — домену неизвестно.
    """

    async def verify(self, token: str) -> VerifiedIdentity: ...
