from datetime import (
    datetime,
)
from pathlib import (
    Path,
)
from uuid import (
    UUID,
)

from pydantic import (
    BaseModel,
    Field,
)

from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import (
    EgressPolicy,
    VcsProvider,
)


class RegisterRepositoryRequest(BaseModel):
    tenant_id: UUID
    name: str = Field(min_length=1, max_length=255)
    vcs_provider: VcsProvider = VcsProvider.LOCAL
    local_path: Path
    remote_url: str | None = None
    default_branch: str = "main"
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY


class RepositoryResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    vcs_provider: VcsProvider
    remote_url: str | None
    default_branch: str
    local_path: Path
    egress_policy: EgressPolicy
    created_at: datetime

    @classmethod
    def from_domain(cls, repository: CodeRepository) -> "RepositoryResponse":
        return cls(
            id=repository.id,
            tenant_id=repository.tenant_id,
            name=repository.name,
            vcs_provider=repository.vcs_provider,
            remote_url=repository.remote_url,
            default_branch=repository.default_branch,
            local_path=repository.local_path,
            egress_policy=repository.egress_policy,
            created_at=repository.created_at,
        )
