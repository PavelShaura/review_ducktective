from ducktective.core.tenancy.entities import (
    Invitation,
    Tenant,
    UserAccount,
)
from ducktective.core.types import (
    InvitationId,
    TenantId,
    UserId,
)
from ducktective.storage.models.tenancy import (
    TenantInvitationModel,
    TenantModel,
    UserAccountModel,
)


def tenant_to_domain(model: TenantModel) -> Tenant:
    return Tenant(
        id=TenantId(model.id),
        slug=model.slug,
        name=model.name,
        created_at=model.created_at,
    )


def tenant_to_model(tenant: Tenant) -> TenantModel:
    return TenantModel(
        id=tenant.id,
        slug=tenant.slug,
        name=tenant.name,
        settings={},
        created_at=tenant.created_at,
    )


def apply_tenant_changes(model: TenantModel, tenant: Tenant) -> None:
    model.name = tenant.name


def account_to_domain(model: UserAccountModel) -> UserAccount:
    return UserAccount(
        id=UserId(model.id),
        tenant_id=TenantId(model.tenant_id),
        external_issuer=model.external_issuer,
        external_subject=model.external_subject,
        email=model.email,
        role=model.role,
        created_at=model.created_at,
        last_seen_at=model.last_seen_at,
    )


def account_to_model(account: UserAccount) -> UserAccountModel:
    return UserAccountModel(
        id=account.id,
        tenant_id=account.tenant_id,
        external_issuer=account.external_issuer,
        external_subject=account.external_subject,
        email=account.email,
        role=account.role,
        created_at=account.created_at,
        last_seen_at=account.last_seen_at,
    )


def apply_account_changes(model: UserAccountModel, account: UserAccount) -> None:
    model.email = account.email
    model.role = account.role
    model.last_seen_at = account.last_seen_at


def invitation_to_domain(model: TenantInvitationModel) -> Invitation:
    return Invitation(
        id=InvitationId(model.id),
        tenant_id=TenantId(model.tenant_id),
        email=model.email,
        role=model.role,
        token_digest=model.token_digest,
        invited_by=UserId(model.invited_by),
        status=model.status,
        created_at=model.created_at,
        expires_at=model.expires_at,
        accepted_at=model.accepted_at,
        accepted_by=UserId(model.accepted_by) if model.accepted_by is not None else None,
    )


def invitation_to_model(invitation: Invitation) -> TenantInvitationModel:
    return TenantInvitationModel(
        id=invitation.id,
        tenant_id=invitation.tenant_id,
        email=invitation.email,
        role=invitation.role,
        token_digest=invitation.token_digest,
        invited_by=invitation.invited_by,
        status=invitation.status,
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        accepted_by=invitation.accepted_by,
    )


def apply_invitation_changes(model: TenantInvitationModel, invitation: Invitation) -> None:
    model.status = invitation.status
    model.accepted_at = invitation.accepted_at
    model.accepted_by = invitation.accepted_by
