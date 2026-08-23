from datetime import (
    UTC,
    datetime,
    timedelta,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.core.exceptions import (
    AccessDeniedError,
    InvariantViolationError,
)
from ducktective.core.tenancy.entities import (
    Invitation,
    Tenant,
    UserAccount,
)
from ducktective.core.tenancy.events import (
    InvitationAccepted,
    MemberJoined,
    MemberRoleChanged,
    TenantCreated,
)
from ducktective.core.tenancy.membership import (
    ensure_owner_remains,
)
from ducktective.core.tenancy.value_objects import (
    InvitationStatus,
    InvitationToken,
    TenantRole,
    VerifiedIdentity,
)
from ducktective.core.types import (
    TenantId,
    UserId,
)


def identity(email: str = "owner@example.com", subject: str = "sub-1") -> VerifiedIdentity:
    return VerifiedIdentity(
        issuer="https://keycloak/realms/ducktective", subject=subject, email=email
    )


def member(role: TenantRole, *, tenant_id: TenantId, subject: str) -> UserAccount:
    return UserAccount.provision(
        tenant_id=tenant_id,
        identity=identity(email=f"{subject}@example.com", subject=subject),
        role=role,
    )


def test_tenant_creation_records_event() -> None:
    tenant = Tenant.create(slug="Acme-Corp", name="  Acme  ")

    assert tenant.slug == "acme-corp"
    assert tenant.name == "Acme"
    assert [type(event) for event in tenant.pull_events()] == [TenantCreated]


@pytest.mark.parametrize("slug", ["a", "Про-ект", "acme_corp", "-acme", ""])
def test_slug_is_validated(slug: str) -> None:
    with pytest.raises(InvariantViolationError):
        Tenant.create(slug=slug, name="Acme")


def test_provisioned_member_normalizes_email_and_announces_itself() -> None:
    tenant_id = TenantId(uuid4())

    account = UserAccount.provision(
        tenant_id=tenant_id,
        identity=identity(email="  Owner@Example.COM "),
        role=TenantRole.OWNER,
    )

    assert account.email == "owner@example.com"
    assert account.is_owner
    assert [type(event) for event in account.pull_events()] == [MemberJoined]


def test_member_cannot_manage_organization() -> None:
    account = member(TenantRole.MEMBER, tenant_id=TenantId(uuid4()), subject="member")

    with pytest.raises(AccessDeniedError):
        account.ensure_manages_organization()


def test_role_change_records_previous_and_current() -> None:
    account = member(TenantRole.MEMBER, tenant_id=TenantId(uuid4()), subject="member")
    account.pull_events()

    account.change_role(TenantRole.OWNER)

    events = account.pull_events()
    assert [type(event) for event in events] == [MemberRoleChanged]
    changed = events[0]
    assert isinstance(changed, MemberRoleChanged)
    assert changed.previous_role is TenantRole.MEMBER
    assert changed.current_role is TenantRole.OWNER


def test_last_owner_cannot_be_demoted() -> None:
    tenant_id = TenantId(uuid4())
    owner = member(TenantRole.OWNER, tenant_id=tenant_id, subject="owner")
    plain = member(TenantRole.MEMBER, tenant_id=tenant_id, subject="member")

    ensure_owner_remains([owner, plain], changing=plain)

    with pytest.raises(InvariantViolationError):
        ensure_owner_remains([owner, plain], changing=owner)


def test_owner_can_be_demoted_when_another_owner_remains() -> None:
    tenant_id = TenantId(uuid4())
    first = member(TenantRole.OWNER, tenant_id=tenant_id, subject="first")
    second = member(TenantRole.OWNER, tenant_id=tenant_id, subject="second")

    ensure_owner_remains([first, second], changing=first)


def test_invitation_keeps_only_the_digest() -> None:
    token = InvitationToken.issue()
    invitation = Invitation.issue(
        tenant_id=TenantId(uuid4()),
        email="Guest@Example.com",
        role=TenantRole.MEMBER,
        invited_by=UserId(uuid4()),
        token=token,
    )

    assert invitation.email == "guest@example.com"
    assert invitation.token_digest != token.value
    assert token.matches(invitation.token_digest)


def test_invitation_is_accepted_by_its_addressee() -> None:
    token = InvitationToken.issue()
    invitation = Invitation.issue(
        tenant_id=TenantId(uuid4()),
        email="guest@example.com",
        role=TenantRole.MEMBER,
        invited_by=UserId(uuid4()),
        token=token,
    )
    invitation.pull_events()
    user_id = UserId(uuid4())

    invitation.accept(
        identity=identity(email="Guest@example.com", subject="sub-guest"),
        user_id=user_id,
        at=datetime.now(UTC),
    )

    assert invitation.status is InvitationStatus.ACCEPTED
    assert invitation.accepted_by == user_id
    assert [type(event) for event in invitation.pull_events()] == [InvitationAccepted]


def test_invitation_rejects_another_address() -> None:
    invitation = Invitation.issue(
        tenant_id=TenantId(uuid4()),
        email="guest@example.com",
        role=TenantRole.MEMBER,
        invited_by=UserId(uuid4()),
        token=InvitationToken.issue(),
    )

    with pytest.raises(AccessDeniedError):
        invitation.accept(
            identity=identity(email="someone@example.com", subject="sub-other"),
            user_id=UserId(uuid4()),
            at=datetime.now(UTC),
        )


def test_expired_invitation_is_not_accepted() -> None:
    invitation = Invitation.issue(
        tenant_id=TenantId(uuid4()),
        email="guest@example.com",
        role=TenantRole.MEMBER,
        invited_by=UserId(uuid4()),
        token=InvitationToken.issue(),
        lifetime=timedelta(seconds=1),
    )

    with pytest.raises(InvariantViolationError):
        invitation.accept(
            identity=identity(email="guest@example.com", subject="sub-guest"),
            user_id=UserId(uuid4()),
            at=datetime.now(UTC) + timedelta(seconds=2),
        )


def test_accepted_invitation_cannot_be_revoked_or_reused() -> None:
    invitation = Invitation.issue(
        tenant_id=TenantId(uuid4()),
        email="guest@example.com",
        role=TenantRole.MEMBER,
        invited_by=UserId(uuid4()),
        token=InvitationToken.issue(),
    )
    invitation.accept(
        identity=identity(email="guest@example.com", subject="sub-guest"),
        user_id=UserId(uuid4()),
        at=datetime.now(UTC),
    )

    with pytest.raises(InvariantViolationError):
        invitation.revoke()
    with pytest.raises(InvariantViolationError):
        invitation.accept(
            identity=identity(email="guest@example.com", subject="sub-guest"),
            user_id=UserId(uuid4()),
            at=datetime.now(UTC),
        )
