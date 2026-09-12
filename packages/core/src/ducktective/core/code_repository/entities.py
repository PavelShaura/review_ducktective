from dataclasses import (
    dataclass,
)
from datetime import (
    UTC,
    datetime,
)
from pathlib import (
    Path,
)
from typing import (
    Self,
)
from uuid import (
    uuid4,
)

from ducktective.core.aggregate import (
    AggregateRoot,
)
from ducktective.core.code_repository.events import (
    CodeRepositoryDeleted,
    CodeRepositoryRegistered,
    EgressPolicyChanged,
)
from ducktective.core.code_repository.value_objects import (
    EgressPolicy,
    VcsProvider,
)
from ducktective.core.exceptions import (
    InvariantViolationError,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)


@dataclass(kw_only=True)
class CodeRepository(AggregateRoot):
    """Кодовая база, поставленная на индексацию и ревью.

    Политика egress — инвариант безопасности: она определяет, может ли содержимое
    этого репозитория попасть во внешнюю модель.
    """

    id: RepositoryId
    tenant_id: TenantId
    name: str
    vcs_provider: VcsProvider
    remote_url: str | None
    default_branch: str
    local_path: Path
    egress_policy: EgressPolicy
    created_at: datetime
    embedding_backend: str | None = None
    """Ключ сервера эмбеддингов, которым считался индекс.

    По нему поиск находит набор векторов репозитория; пусто — сервер
    по умолчанию.
    """

    @classmethod
    def register(
        cls,
        *,
        tenant_id: TenantId,
        name: str,
        vcs_provider: VcsProvider,
        local_path: Path,
        remote_url: str | None = None,
        default_branch: str = "main",
        egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY,
    ) -> Self:
        if not name.strip():
            raise InvariantViolationError("Имя репозитория не может быть пустым")
        if vcs_provider is not VcsProvider.LOCAL and not remote_url:
            raise InvariantViolationError(
                f"Для провайдера {vcs_provider} требуется адрес удалённого репозитория"
            )

        repository = cls(
            id=RepositoryId(uuid4()),
            tenant_id=tenant_id,
            name=name.strip(),
            vcs_provider=vcs_provider,
            remote_url=remote_url,
            default_branch=default_branch,
            local_path=local_path,
            egress_policy=egress_policy,
            created_at=datetime.now(UTC),
        )
        repository.record_event(
            CodeRepositoryRegistered(
                repository_id=repository.id,
                tenant_id=repository.tenant_id,
                name=repository.name,
            )
        )
        return repository

    @property
    def cloud_processing_allowed(self) -> bool:
        return self.egress_policy is EgressPolicy.ALLOW_CLOUD

    def choose_embedding_backend(self, key: str | None) -> None:
        self.embedding_backend = key or None

    def change_egress_policy(self, policy: EgressPolicy) -> None:
        if policy is self.egress_policy:
            return

        previous_policy = self.egress_policy
        self.egress_policy = policy
        self.record_event(
            EgressPolicyChanged(
                repository_id=self.id,
                previous_policy=previous_policy,
                current_policy=policy,
            )
        )

    def record_deletion(self) -> None:
        """Отмечает удаление репозитория.

        Событие порождается до самого удаления: после него агрегата уже нет,
        а подписчикам знать о случившемся нужно.
        """
        self.record_event(
            CodeRepositoryDeleted(
                repository_id=self.id,
                tenant_id=self.tenant_id,
                name=self.name,
            )
        )
