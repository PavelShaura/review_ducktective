from dataclasses import (
    dataclass,
)
from datetime import (
    datetime,
)

from ducktective.core.types import (
    TenantId,
    UserId,
)


@dataclass(kw_only=True)
class Tenant:
    id: TenantId
    slug: str
    name: str
    created_at: datetime


@dataclass(kw_only=True)
class UserAccount:
    id: UserId
    tenant_id: TenantId
    external_subject: str
    email: str
    role: str
    created_at: datetime
