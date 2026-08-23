from uuid import (
    UUID,
)

from fastapi import (
    APIRouter,
    HTTPException,
    status,
)

from ducktective.api.dependencies import (
    EventPublisherDependency,
    UnitOfWorkDependency,
)
from ducktective.api.schemas.organization import (
    AcceptInvitationRequest,
    ChangeMemberRoleRequest,
    CreateOrganizationRequest,
    CurrentUserResponse,
    InvitationResponse,
    InviteMemberRequest,
    IssuedInvitationResponse,
    MemberResponse,
    OrganizationResponse,
)
from ducktective.api.security import (
    IdentityDependency,
    MemberDependency,
    OwnerDependency,
    SignedInUserDependency,
)
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
    ListInvitations,
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
from ducktective.core.exceptions import (
    AccessDeniedError,
    EntityNotFoundError,
    InvariantViolationError,
)
from ducktective.core.types import (
    InvitationId,
    UserId,
)


router = APIRouter(tags=["organization"])


@router.get("/auth/me", response_model=CurrentUserResponse)
async def read_current_user(
    user: SignedInUserDependency,
    unit_of_work: UnitOfWorkDependency,
) -> CurrentUserResponse:
    """Кто вошёл и есть ли у него организация."""
    if user.account is None:
        return CurrentUserResponse(
            email=user.identity.email,
            subject=user.identity.subject,
        )

    async with unit_of_work:
        tenant = await unit_of_work.tenants.get(user.account.tenant_id)

    return CurrentUserResponse(
        email=user.identity.email,
        subject=user.identity.subject,
        organization=OrganizationResponse.from_domain(tenant),
        member=MemberResponse.from_domain(user.account),
    )


@router.post(
    "/organizations",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization(
    payload: CreateOrganizationRequest,
    identity: IdentityDependency,
    unit_of_work: UnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> OrganizationResponse:
    use_case = CreateOrganization(unit_of_work, event_publisher)

    try:
        created = await use_case.execute(
            CreateOrganizationCommand(
                identity=identity,
                slug=payload.slug,
                name=payload.name,
            )
        )
    except OrganizationSlugTakenError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except AlreadyInOrganizationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except InvariantViolationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error

    return OrganizationResponse.from_domain(created.tenant)


@router.get("/organization/members", response_model=list[MemberResponse])
async def list_members(
    member: MemberDependency,
    unit_of_work: UnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> list[MemberResponse]:
    use_case = ListMembers(unit_of_work, event_publisher)
    members = await use_case.execute(member.id)
    return [MemberResponse.from_domain(account) for account in members]


@router.patch("/organization/members/{member_id}", response_model=MemberResponse)
async def change_member_role(
    member_id: UUID,
    payload: ChangeMemberRoleRequest,
    owner: OwnerDependency,
    unit_of_work: UnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> MemberResponse:
    use_case = ChangeMemberRole(unit_of_work, event_publisher)

    try:
        changed = await use_case.execute(
            ChangeMemberRoleCommand(
                actor_id=owner.id,
                member_id=UserId(member_id),
                role=payload.role,
            )
        )
    except MemberNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except InvariantViolationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except AccessDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    return MemberResponse.from_domain(changed)


@router.delete("/organization/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    member_id: UUID,
    owner: OwnerDependency,
    unit_of_work: UnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> None:
    use_case = RemoveMember(unit_of_work, event_publisher)

    try:
        await use_case.execute(RemoveMemberCommand(actor_id=owner.id, member_id=UserId(member_id)))
    except MemberNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except InvariantViolationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except AccessDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error


@router.get("/organization/invitations", response_model=list[InvitationResponse])
async def list_invitations(
    owner: OwnerDependency,
    unit_of_work: UnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> list[InvitationResponse]:
    use_case = ListInvitations(unit_of_work, event_publisher)
    invitations = await use_case.execute(owner.tenant_id, actor_id=owner.id)
    return [InvitationResponse.from_domain(invitation) for invitation in invitations]


@router.post(
    "/organization/invitations",
    response_model=IssuedInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    payload: InviteMemberRequest,
    owner: OwnerDependency,
    unit_of_work: UnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> IssuedInvitationResponse:
    """Выписывает приглашение и один раз показывает его секрет."""
    use_case = InviteMember(unit_of_work, event_publisher)

    try:
        issued = await use_case.execute(
            InviteMemberCommand(actor_id=owner.id, email=payload.email, role=payload.role)
        )
    except MemberAlreadyInvitedError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except InvariantViolationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    except AccessDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    return IssuedInvitationResponse.from_issued(issued)


@router.delete(
    "/organization/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_invitation(
    invitation_id: UUID,
    owner: OwnerDependency,
    unit_of_work: UnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> None:
    use_case = RevokeInvitation(unit_of_work, event_publisher)

    try:
        await use_case.execute(
            RevokeInvitationCommand(
                actor_id=owner.id,
                invitation_id=InvitationId(invitation_id),
            )
        )
    except (EntityNotFoundError, InvitationNotFoundError) as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except InvariantViolationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except AccessDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error


@router.post("/invitations/accept", response_model=MemberResponse)
async def accept_invitation(
    payload: AcceptInvitationRequest,
    identity: IdentityDependency,
    unit_of_work: UnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> MemberResponse:
    """Принимает приглашение тем, кто вошёл через провайдера личности."""
    use_case = AcceptInvitation(unit_of_work, event_publisher)

    try:
        account = await use_case.execute(
            AcceptInvitationCommand(identity=identity, token=payload.token)
        )
    except InvitationNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except AlreadyInOrganizationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except AccessDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except InvariantViolationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error

    return MemberResponse.from_domain(account)
