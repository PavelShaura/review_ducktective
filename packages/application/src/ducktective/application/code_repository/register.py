from dataclasses import (
    dataclass,
)
from pathlib import (
    Path,
)

from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    ApplicationError,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import (
    EgressPolicy,
    VcsProvider,
)
from ducktective.core.types import (
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class RegisterCodeRepositoryCommand:
    tenant_id: TenantId
    name: str
    vcs_provider: VcsProvider
    local_path: Path
    remote_url: str | None = None
    default_branch: str = "main"
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY


class RepositoryAlreadyRegisteredError(ApplicationError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Репозиторий с именем «{name}» уже зарегистрирован")
        self.name = name


class RegisterCodeRepository(TransactionalUseCase):
    """Регистрация кодовой базы для индексации и ревью."""

    async def execute(self, command: RegisterCodeRepositoryCommand) -> CodeRepository:
        async with self._unit_of_work:
            existing = await self._unit_of_work.code_repositories.find_by_name(
                command.tenant_id,
                command.name,
            )
            if existing is not None:
                raise RepositoryAlreadyRegisteredError(command.name)

            repository = CodeRepository.register(
                tenant_id=command.tenant_id,
                name=command.name,
                vcs_provider=command.vcs_provider,
                local_path=command.local_path,
                remote_url=command.remote_url,
                default_branch=command.default_branch,
                egress_policy=command.egress_policy,
            )
            self._unit_of_work.code_repositories.add(repository)
            await self._commit_and_publish()

        return repository
