from dataclasses import (
    dataclass,
)
from datetime import (
    UTC,
    datetime,
)

from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    ApplicationError,
)
from ducktective.application.tenancy.create_organization import (
    AlreadyInOrganizationError,
)
from ducktective.core.tenancy.entities import (
    Invitation,
    UserAccount,
)
from ducktective.core.tenancy.value_objects import (
    InvitationToken,
    TenantRole,
    VerifiedIdentity,
)
from ducktective.core.types import (
    InvitationId,
    TenantId,
    UserId,
)


@dataclass(frozen=True, kw_only=True)
class InviteMemberCommand:
    actor_id: UserId
    email: str
    role: TenantRole = TenantRole.MEMBER


@dataclass(frozen=True, kw_only=True)
class IssuedInvitation:
    """Приглашение и его секрет.

    Секрет возвращается ровно один раз — в ответе на создание: в базе лежит
    отпечаток, и показать ссылку второй раз нельзя даже владельцу.
    """

    invitation: Invitation
    token: InvitationToken


class MemberAlreadyInvitedError(ApplicationError):
    def __init__(self, email: str) -> None:
        super().__init__(f"Приглашение на адрес {email} уже выписано")
        self.email = email


class InvitationNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__("Приглашение не найдено или больше не действует")


class InviteMember(TransactionalUseCase):
    """Приглашение в организацию приглашающего.

    Организация берётся из членства зовущего, а не из запроса: иначе владелец
    одной организации выписывал бы приглашения в чужую.
    """

    async def execute(self, command: InviteMemberCommand) -> IssuedInvitation:
        async with self._unit_of_work:
            actor = await self._unit_of_work.user_accounts.get(command.actor_id)
            actor.ensure_manages_organization()

            email = command.email.strip().lower()
            pending = await self._unit_of_work.invitations.list_pending(actor.tenant_id)
            now = datetime.now(UTC)
            if any(
                invitation.email == email and invitation.is_valid_at(now) for invitation in pending
            ):
                raise MemberAlreadyInvitedError(email)

            token = InvitationToken.issue()
            invitation = Invitation.issue(
                tenant_id=actor.tenant_id,
                email=email,
                role=command.role,
                invited_by=actor.id,
                token=token,
            )
            self._unit_of_work.invitations.add(invitation)
            await self._commit_and_publish()

        return IssuedInvitation(invitation=invitation, token=token)


@dataclass(frozen=True, kw_only=True)
class AcceptInvitationCommand:
    identity: VerifiedIdentity
    token: str


class AcceptInvitation(TransactionalUseCase):
    """Принятие приглашения тем, кто вошёл через провайдера личности.

    Просроченное, отозванное и несуществующее приглашение отвечают одинаково:
    отличать их значит рассказывать предъявителю чужой ссылки, была ли она
    когда-то настоящей.
    """

    async def execute(self, command: AcceptInvitationCommand) -> UserAccount:
        async with self._unit_of_work:
            existing_membership = await self._unit_of_work.user_accounts.find_by_identity(
                issuer=command.identity.issuer,
                subject=command.identity.subject,
            )
            if existing_membership is not None:
                raise AlreadyInOrganizationError

            token = InvitationToken(command.token)
            invitation = await self._unit_of_work.invitations.find_by_token_digest(token.digest)
            now = datetime.now(UTC)
            if invitation is None or not invitation.is_valid_at(now):
                raise InvitationNotFoundError

            account = UserAccount.provision(
                tenant_id=invitation.tenant_id,
                identity=command.identity,
                role=invitation.role,
            )
            invitation.accept(identity=command.identity, user_id=account.id, at=now)
            self._unit_of_work.user_accounts.add(account)
            await self._commit_and_publish()

        return account


@dataclass(frozen=True, kw_only=True)
class RevokeInvitationCommand:
    actor_id: UserId
    invitation_id: InvitationId


class RevokeInvitation(TransactionalUseCase):
    async def execute(self, command: RevokeInvitationCommand) -> None:
        async with self._unit_of_work:
            actor = await self._unit_of_work.user_accounts.get(command.actor_id)
            actor.ensure_manages_organization()

            invitation = await self._unit_of_work.invitations.get(command.invitation_id)
            if invitation.tenant_id != actor.tenant_id:
                raise InvitationNotFoundError

            invitation.revoke()
            await self._commit_and_publish()


class ListInvitations(TransactionalUseCase):
    async def execute(self, tenant_id: TenantId, *, actor_id: UserId) -> list[Invitation]:
        async with self._unit_of_work:
            actor = await self._unit_of_work.user_accounts.get(actor_id)
            actor.ensure_manages_organization()
            if actor.tenant_id != tenant_id:
                return []

            return await self._unit_of_work.invitations.list_pending(tenant_id)
