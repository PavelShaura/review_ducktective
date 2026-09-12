from pathlib import (
    Path,
)

from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)
from ducktective.storage.models.code_repository import (
    CodeRepositoryModel,
)


def to_domain(model: CodeRepositoryModel) -> CodeRepository:
    return CodeRepository(
        id=RepositoryId(model.id),
        tenant_id=TenantId(model.tenant_id),
        name=model.name,
        vcs_provider=model.vcs_provider,
        remote_url=model.remote_url,
        default_branch=model.default_branch,
        local_path=Path(model.local_path),
        egress_policy=model.egress_policy,
        created_at=model.created_at,
        embedding_backend=model.embedding_backend,
    )


def to_model(repository: CodeRepository) -> CodeRepositoryModel:
    return CodeRepositoryModel(
        id=repository.id,
        tenant_id=repository.tenant_id,
        name=repository.name,
        vcs_provider=repository.vcs_provider,
        remote_url=repository.remote_url,
        default_branch=repository.default_branch,
        local_path=str(repository.local_path),
        egress_policy=repository.egress_policy,
        created_at=repository.created_at,
        embedding_backend=repository.embedding_backend,
    )


def apply_changes(model: CodeRepositoryModel, repository: CodeRepository) -> None:
    model.name = repository.name
    model.vcs_provider = repository.vcs_provider
    model.remote_url = repository.remote_url
    model.default_branch = repository.default_branch
    model.local_path = str(repository.local_path)
    model.egress_policy = repository.egress_policy
    model.embedding_backend = repository.embedding_backend
