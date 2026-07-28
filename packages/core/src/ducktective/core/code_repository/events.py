from dataclasses import (
    dataclass,
)

from ducktective.core.code_repository.value_objects import (
    EgressPolicy,
)
from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class CodeRepositoryRegistered(DomainEvent):
    repository_id: RepositoryId
    tenant_id: TenantId
    name: str


@dataclass(frozen=True, kw_only=True)
class EgressPolicyChanged(DomainEvent):
    repository_id: RepositoryId
    previous_policy: EgressPolicy
    current_policy: EgressPolicy


@dataclass(frozen=True, kw_only=True)
class CodeRepositoryDeleted(DomainEvent):
    repository_id: RepositoryId
    tenant_id: TenantId
    name: str
