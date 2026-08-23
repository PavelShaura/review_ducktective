from dataclasses import (
    dataclass,
)

from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.tenancy.value_objects import (
    TenantRole,
)
from ducktective.core.types import (
    InvitationId,
    TenantId,
    UserId,
)


@dataclass(frozen=True, kw_only=True)
class TenantCreated(DomainEvent):
    tenant_id: TenantId
    slug: str


@dataclass(frozen=True, kw_only=True)
class MemberJoined(DomainEvent):
    tenant_id: TenantId
    user_id: UserId
    role: TenantRole


@dataclass(frozen=True, kw_only=True)
class MemberInvited(DomainEvent):
    invitation_id: InvitationId
    tenant_id: TenantId
    email: str
    role: TenantRole


@dataclass(frozen=True, kw_only=True)
class InvitationAccepted(DomainEvent):
    invitation_id: InvitationId
    tenant_id: TenantId
    user_id: UserId


@dataclass(frozen=True, kw_only=True)
class InvitationRevoked(DomainEvent):
    invitation_id: InvitationId
    tenant_id: TenantId


@dataclass(frozen=True, kw_only=True)
class MemberRoleChanged(DomainEvent):
    tenant_id: TenantId
    user_id: UserId
    previous_role: TenantRole
    current_role: TenantRole


@dataclass(frozen=True, kw_only=True)
class MemberRemoved(DomainEvent):
    tenant_id: TenantId
    user_id: UserId
