from uuid import (
    uuid4,
)

import pytest

from ducktective.application.tenancy.create_organization import (
    AlreadyInOrganizationError,
    CreateOrganization,
    CreateOrganizationCommand,
    OrganizationSlugTakenError,
)
from ducktective.application.tenancy.invitations import (
    AcceptInvitation,
    AcceptInvitationCommand,
    InvitationNotFoundError,
    InviteMember,
    InviteMemberCommand,
    MemberAlreadyInvitedError,
    RevokeInvitation,
    RevokeInvitationCommand,
)
from ducktective.application.tenancy.members import (
    ChangeMemberRole,
    ChangeMemberRoleCommand,
    ListMembers,
    MemberNotFoundError,
    RemoveMember,
    RemoveMemberCommand,
)
from ducktective.application.tenancy.sign_in import (
    ResolveSignedInUser,
)
from ducktective.core.exceptions import (
    AccessDeniedError,
    InvariantViolationError,
)
from ducktective.core.tenancy.entities import (
    Tenant,
    UserAccount,
)
from ducktective.core.tenancy.value_objects import (
    InvitationStatus,
    TenantRole,
    VerifiedIdentity,
)
from ducktective.core.types import (
    UserId,
)
from tests.fakes import (
    FakeEventPublisher,
    FakeUnitOfWork,
)


ISSUER = "https://keycloak/realms/ducktective"


def identity(subject: str, email: str) -> VerifiedIdentity:
    return VerifiedIdentity(issuer=ISSUER, subject=subject, email=email)


async def create_organization(
    unit_of_work: FakeUnitOfWork,
    publisher: FakeEventPublisher,
    *,
    owner_email: str = "owner@example.com",
) -> tuple[Tenant, UserAccount]:
    use_case = CreateOrganization(unit_of_work, publisher)
    created = await use_case.execute(
        CreateOrganizationCommand(
            identity=identity("sub-owner", owner_email),
            slug="acme",
            name="Acme",
        )
    )
    return created.tenant, created.owner


async def test_organization_creator_becomes_owner() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()

    tenant, owner = await create_organization(unit_of_work, publisher)

    assert owner.tenant_id == tenant.id
    assert owner.role is TenantRole.OWNER
    assert unit_of_work.commit_calls == 1
    assert {type(event).__name__ for event in publisher.published} == {
        "TenantCreated",
        "MemberJoined",
    }


async def test_slug_is_taken_once() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    await create_organization(unit_of_work, publisher)

    use_case = CreateOrganization(unit_of_work, publisher)
    with pytest.raises(OrganizationSlugTakenError):
        await use_case.execute(
            CreateOrganizationCommand(
                identity=identity("sub-other", "other@example.com"),
                slug="acme",
                name="Acme Two",
            )
        )


async def test_second_organization_is_refused_for_the_same_identity() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    await create_organization(unit_of_work, publisher)

    use_case = CreateOrganization(unit_of_work, publisher)
    with pytest.raises(AlreadyInOrganizationError):
        await use_case.execute(
            CreateOrganizationCommand(
                identity=identity("sub-owner", "owner@example.com"),
                slug="acme-two",
                name="Acme Two",
            )
        )


async def test_signed_in_user_without_membership_is_not_an_error() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()

    resolved = await ResolveSignedInUser(unit_of_work, publisher).execute(
        identity("sub-nobody", "nobody@example.com")
    )

    assert not resolved.belongs_to_organization
    assert resolved.account is None


async def test_sign_in_follows_the_email_from_the_provider() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    await create_organization(unit_of_work, publisher)

    resolved = await ResolveSignedInUser(unit_of_work, publisher).execute(
        identity("sub-owner", "renamed@example.com")
    )

    assert resolved.account is not None
    assert resolved.account.email == "renamed@example.com"
    assert resolved.account.last_seen_at is not None


async def test_invitation_travels_from_owner_to_a_new_member() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant, owner = await create_organization(unit_of_work, publisher)

    issued = await InviteMember(unit_of_work, publisher).execute(
        InviteMemberCommand(actor_id=owner.id, email="Guest@Example.com")
    )
    account = await AcceptInvitation(unit_of_work, publisher).execute(
        AcceptInvitationCommand(
            identity=identity("sub-guest", "guest@example.com"),
            token=issued.token.value,
        )
    )

    assert account.tenant_id == tenant.id
    assert account.role is TenantRole.MEMBER
    assert issued.invitation.status is InvitationStatus.ACCEPTED


async def test_member_cannot_invite() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    _, owner = await create_organization(unit_of_work, publisher)
    issued = await InviteMember(unit_of_work, publisher).execute(
        InviteMemberCommand(actor_id=owner.id, email="guest@example.com")
    )
    guest = await AcceptInvitation(unit_of_work, publisher).execute(
        AcceptInvitationCommand(
            identity=identity("sub-guest", "guest@example.com"),
            token=issued.token.value,
        )
    )

    with pytest.raises(AccessDeniedError):
        await InviteMember(unit_of_work, publisher).execute(
            InviteMemberCommand(actor_id=guest.id, email="third@example.com")
        )


async def test_same_address_is_not_invited_twice() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    _, owner = await create_organization(unit_of_work, publisher)
    await InviteMember(unit_of_work, publisher).execute(
        InviteMemberCommand(actor_id=owner.id, email="guest@example.com")
    )

    with pytest.raises(MemberAlreadyInvitedError):
        await InviteMember(unit_of_work, publisher).execute(
            InviteMemberCommand(actor_id=owner.id, email="guest@example.com")
        )


async def test_revoked_invitation_does_not_work() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    _, owner = await create_organization(unit_of_work, publisher)
    issued = await InviteMember(unit_of_work, publisher).execute(
        InviteMemberCommand(actor_id=owner.id, email="guest@example.com")
    )

    await RevokeInvitation(unit_of_work, publisher).execute(
        RevokeInvitationCommand(actor_id=owner.id, invitation_id=issued.invitation.id)
    )

    with pytest.raises(InvitationNotFoundError):
        await AcceptInvitation(unit_of_work, publisher).execute(
            AcceptInvitationCommand(
                identity=identity("sub-guest", "guest@example.com"),
                token=issued.token.value,
            )
        )


async def test_unknown_token_is_refused() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    await create_organization(unit_of_work, publisher)

    with pytest.raises(InvitationNotFoundError):
        await AcceptInvitation(unit_of_work, publisher).execute(
            AcceptInvitationCommand(
                identity=identity("sub-guest", "guest@example.com"),
                token="made-up",
            )
        )


async def test_last_owner_is_neither_demoted_nor_removed() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    _, owner = await create_organization(unit_of_work, publisher)

    with pytest.raises(InvariantViolationError):
        await ChangeMemberRole(unit_of_work, publisher).execute(
            ChangeMemberRoleCommand(
                actor_id=owner.id,
                member_id=owner.id,
                role=TenantRole.MEMBER,
            )
        )
    with pytest.raises(InvariantViolationError):
        await RemoveMember(unit_of_work, publisher).execute(
            RemoveMemberCommand(actor_id=owner.id, member_id=owner.id)
        )


async def test_member_of_another_organization_is_not_found() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    _, owner = await create_organization(unit_of_work, publisher)

    with pytest.raises(MemberNotFoundError):
        await ChangeMemberRole(unit_of_work, publisher).execute(
            ChangeMemberRoleCommand(
                actor_id=owner.id,
                member_id=UserId(uuid4()),
                role=TenantRole.MEMBER,
            )
        )


async def test_members_are_listed_within_the_organization() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    _, owner = await create_organization(unit_of_work, publisher)
    issued = await InviteMember(unit_of_work, publisher).execute(
        InviteMemberCommand(actor_id=owner.id, email="guest@example.com")
    )
    await AcceptInvitation(unit_of_work, publisher).execute(
        AcceptInvitationCommand(
            identity=identity("sub-guest", "guest@example.com"),
            token=issued.token.value,
        )
    )

    members = await ListMembers(unit_of_work, publisher).execute(owner.id)

    assert {account.email for account in members} == {
        "owner@example.com",
        "guest@example.com",
    }
