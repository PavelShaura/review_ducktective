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
    UserAccount,
)
from ducktective.core.tenancy.membership import (
    ensure_owner_remains,
)
from ducktective.core.tenancy.value_objects import (
    TenantRole,
)
from ducktective.core.types import (
    UserId,
)


class MemberNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__("Участник не найден")


@dataclass(frozen=True, kw_only=True)
class ChangeMemberRoleCommand:
    actor_id: UserId
    member_id: UserId
    role: TenantRole


@dataclass(frozen=True, kw_only=True)
class RemoveMemberCommand:
    actor_id: UserId
    member_id: UserId


class ListMembers(TransactionalUseCase):
    async def execute(self, actor_id: UserId) -> list[UserAccount]:
        async with self._unit_of_work:
            actor = await self._unit_of_work.user_accounts.get(actor_id)
            return await self._unit_of_work.user_accounts.list_for_tenant(actor.tenant_id)


class ChangeMemberRole(TransactionalUseCase):
    """Смена роли участника владельцем организации.

    Понижение последнего владельца отклоняется доменным правилом: организация
    с репозиториями, которые некому передать, остаётся без того, кто вправе
    менять их политику egress.
    """

    async def execute(self, command: ChangeMemberRoleCommand) -> UserAccount:
        async with self._unit_of_work:
            actor = await self._unit_of_work.user_accounts.get(command.actor_id)
            actor.ensure_manages_organization()

            members = await self._unit_of_work.user_accounts.list_for_tenant(actor.tenant_id)
            member = _find_member(members, command.member_id)

            if command.role is not TenantRole.OWNER:
                ensure_owner_remains(members, changing=member)

            member.change_role(command.role)
            await self._commit_and_publish()

        return member


class RemoveMember(TransactionalUseCase):
    async def execute(self, command: RemoveMemberCommand) -> None:
        async with self._unit_of_work:
            actor = await self._unit_of_work.user_accounts.get(command.actor_id)
            actor.ensure_manages_organization()

            members = await self._unit_of_work.user_accounts.list_for_tenant(actor.tenant_id)
            member = _find_member(members, command.member_id)
            ensure_owner_remains(members, changing=member)

            await self._unit_of_work.user_accounts.remove(member)
            await self._commit_and_publish()


def _find_member(members: list[UserAccount], member_id: UserId) -> UserAccount:
    """Участник ищется среди своих же, а не запросом по идентификатору.

    Так чужая учётная запись не отличается от несуществующей: перебор
    идентификаторов иначе рассказывает о составе чужих организаций.
    """
    for member in members:
        if member.id == member_id:
            return member
    raise MemberNotFoundError
