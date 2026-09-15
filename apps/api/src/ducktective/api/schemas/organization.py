from datetime import (
    datetime,
)
from uuid import (
    UUID,
)

from pydantic import (
    BaseModel,
    Field,
)

from ducktective.application.tenancy.invitations import (
    IssuedInvitation,
)
from ducktective.core.tenancy.entities import (
    Invitation,
    Tenant,
    UserAccount,
)
from ducktective.core.tenancy.value_objects import (
    TenantRole,
)


class CreateOrganizationRequest(BaseModel):
    slug: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=255)


class OrganizationResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    created_at: datetime

    @classmethod
    def from_domain(cls, tenant: Tenant) -> "OrganizationResponse":
        return cls(
            id=tenant.id,
            slug=tenant.slug,
            name=tenant.name,
            created_at=tenant.created_at,
        )


class MemberResponse(BaseModel):
    id: UUID
    email: str
    role: TenantRole
    created_at: datetime
    last_seen_at: datetime | None

    @classmethod
    def from_domain(cls, account: UserAccount) -> "MemberResponse":
        return cls(
            id=account.id,
            email=account.email,
            role=account.role,
            created_at=account.created_at,
            last_seen_at=account.last_seen_at,
        )


class CurrentUserResponse(BaseModel):
    """Кто вошёл и куда принадлежит.

    Отсутствие организации — обычное состояние только что зарегистрировавшегося,
    поэтому оно приходит полем, а не ошибкой: фронт по нему решает, показать
    рабочий стол или предложение создать организацию.
    """

    email: str
    subject: str
    organization: OrganizationResponse | None = None
    member: MemberResponse | None = None
    is_installation_admin: bool = False
    """Показывать ли раздел журнала: право не зависит от организации."""


class InviteMemberRequest(BaseModel):
    """Адрес проверяется доменом, а не типом схемы.

    Правило «приглашение отправляется на почтовый адрес» — доменное, и
    вторая его копия в схеме разошлась бы с первой на первой же правке.
    """

    email: str = Field(min_length=3, max_length=320)
    role: TenantRole = TenantRole.MEMBER


class InvitationResponse(BaseModel):
    id: UUID
    email: str
    role: TenantRole
    created_at: datetime
    expires_at: datetime

    @classmethod
    def from_domain(cls, invitation: Invitation) -> "InvitationResponse":
        return cls(
            id=invitation.id,
            email=invitation.email,
            role=invitation.role,
            created_at=invitation.created_at,
            expires_at=invitation.expires_at,
        )


class IssuedInvitationResponse(InvitationResponse):
    """Ответ на создание приглашения — единственное место, где виден секрет.

    В базе лежит только отпечаток, поэтому показать ссылку второй раз нельзя
    ни владельцу, ни кому-либо ещё: не выписав новую, её не восстановить.
    """

    token: str

    @classmethod
    def from_issued(cls, issued: IssuedInvitation) -> "IssuedInvitationResponse":
        invitation = issued.invitation
        return cls(
            id=invitation.id,
            email=invitation.email,
            role=invitation.role,
            created_at=invitation.created_at,
            expires_at=invitation.expires_at,
            token=issued.token.value,
        )


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=1)


class ChangeMemberRoleRequest(BaseModel):
    role: TenantRole
