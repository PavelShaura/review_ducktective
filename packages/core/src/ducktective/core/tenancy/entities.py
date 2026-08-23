import re
from dataclasses import (
    dataclass,
)
from datetime import (
    UTC,
    datetime,
    timedelta,
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
from ducktective.core.exceptions import (
    AccessDeniedError,
    InvariantViolationError,
)
from ducktective.core.tenancy.events import (
    InvitationAccepted,
    InvitationRevoked,
    MemberInvited,
    MemberJoined,
    MemberRoleChanged,
    TenantCreated,
)
from ducktective.core.tenancy.value_objects import (
    InvitationStatus,
    InvitationToken,
    TenantRole,
    VerifiedIdentity,
)
from ducktective.core.types import (
    InvitationId,
    TenantId,
    UserId,
)


SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
DEFAULT_INVITATION_LIFETIME = timedelta(days=7)


@dataclass(kw_only=True)
class Tenant(AggregateRoot):
    """Организация — владелец репозиториев, индексов, прогонов и разговоров.

    Всё, что принадлежит тенанту, отделено от чужого и проверкой в use case,
    и политикой в базе: одного из двух мало. Проверка ловит ошибку логики,
    политика — забытый фильтр в новом репозитории.
    """

    id: TenantId
    slug: str
    name: str
    created_at: datetime

    @classmethod
    def create(cls, *, slug: str, name: str) -> Self:
        normalized_slug = slug.strip().lower()
        if not SLUG_PATTERN.match(normalized_slug):
            raise InvariantViolationError(
                "Короткое имя организации состоит из строчных латинских букв, "
                "цифр и дефисов, длиной от трёх до шестидесяти четырёх знаков"
            )
        if not name.strip():
            raise InvariantViolationError("Название организации не может быть пустым")

        tenant = cls(
            id=TenantId(uuid4()),
            slug=normalized_slug,
            name=name.strip(),
            created_at=datetime.now(UTC),
        )
        tenant.record_event(TenantCreated(tenant_id=tenant.id, slug=tenant.slug))
        return tenant

    def rename(self, name: str) -> None:
        if not name.strip():
            raise InvariantViolationError("Название организации не может быть пустым")
        self.name = name.strip()


@dataclass(kw_only=True)
class UserAccount(AggregateRoot):
    """Участник организации.

    Учётная запись заводится вместе с членством: человек, вошедший через
    провайдера личности, но никуда не принятый, записи здесь не имеет — он
    аутентифицирован и не видит ничего, пока не создаст организацию или
    не примет приглашение.

    Одна личность состоит в одной организации: пара «издатель и субъект»
    уникальна целиком, а не в пределах тенанта. Это ограничение первой
    версии, и снимается оно отделением членства от учётной записи.
    """

    id: UserId
    tenant_id: TenantId
    external_issuer: str
    external_subject: str
    email: str
    role: TenantRole
    created_at: datetime
    last_seen_at: datetime | None = None

    @classmethod
    def provision(
        cls,
        *,
        tenant_id: TenantId,
        identity: VerifiedIdentity,
        role: TenantRole,
    ) -> Self:
        if not identity.subject.strip():
            raise InvariantViolationError("Личность без субъекта не может стать участником")

        account = cls(
            id=UserId(uuid4()),
            tenant_id=tenant_id,
            external_issuer=identity.issuer,
            external_subject=identity.subject,
            email=identity.email.strip().lower(),
            role=role,
            created_at=datetime.now(UTC),
        )
        account.record_event(MemberJoined(tenant_id=tenant_id, user_id=account.id, role=role))
        return account

    @property
    def is_owner(self) -> bool:
        return self.role is TenantRole.OWNER

    def ensure_manages_organization(self) -> None:
        """Право менять состав организации и политику egress репозитория.

        Обе операции меняют то, кто и куда может отправить код, поэтому
        правило одно на двоих.
        """
        if not self.is_owner:
            raise AccessDeniedError("Операция доступна только владельцу организации")

    def change_role(self, role: TenantRole) -> None:
        if role is self.role:
            return

        previous_role = self.role
        self.role = role
        self.record_event(
            MemberRoleChanged(
                tenant_id=self.tenant_id,
                user_id=self.id,
                previous_role=previous_role,
                current_role=role,
            )
        )

    def record_seen(self, at: datetime) -> None:
        self.last_seen_at = at

    def update_email(self, email: str) -> None:
        """Почта следует за провайдером личности: там её меняют, здесь отражают."""
        normalized = email.strip().lower()
        if normalized:
            self.email = normalized


@dataclass(kw_only=True)
class Invitation(AggregateRoot):
    """Приглашение в организацию.

    Живёт отдельным агрегатом, а не списком внутри тенанта: принимает его
    другой человек в другой транзакции, и блокировать ради этого организацию
    целиком незачем.
    """

    id: InvitationId
    tenant_id: TenantId
    email: str
    role: TenantRole
    token_digest: str
    invited_by: UserId
    status: InvitationStatus
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None = None
    accepted_by: UserId | None = None

    @classmethod
    def issue(
        cls,
        *,
        tenant_id: TenantId,
        email: str,
        role: TenantRole,
        invited_by: UserId,
        token: InvitationToken,
        lifetime: timedelta = DEFAULT_INVITATION_LIFETIME,
    ) -> Self:
        normalized_email = email.strip().lower()
        if "@" not in normalized_email:
            raise InvariantViolationError("Приглашение отправляется на почтовый адрес")

        issued_at = datetime.now(UTC)
        invitation = cls(
            id=InvitationId(uuid4()),
            tenant_id=tenant_id,
            email=normalized_email,
            role=role,
            token_digest=token.digest,
            invited_by=invited_by,
            status=InvitationStatus.PENDING,
            created_at=issued_at,
            expires_at=issued_at + lifetime,
        )
        invitation.record_event(
            MemberInvited(
                invitation_id=invitation.id,
                tenant_id=tenant_id,
                email=normalized_email,
                role=role,
            )
        )
        return invitation

    def is_valid_at(self, moment: datetime) -> bool:
        return self.status is InvitationStatus.PENDING and moment < self.expires_at

    def accept(self, *, identity: VerifiedIdentity, user_id: UserId, at: datetime) -> None:
        """Принятие приглашения тем, кому оно выписано.

        Почта сверяется, потому что ссылка попадает в переписку и пересылается
        дальше: без сверки первый получивший её входит в чужую организацию.
        """
        if self.status is not InvitationStatus.PENDING:
            raise InvariantViolationError("Приглашение уже использовано или отозвано")
        if at >= self.expires_at:
            raise InvariantViolationError("Срок приглашения истёк")
        if identity.email.strip().lower() != self.email:
            raise AccessDeniedError("Приглашение выписано на другой почтовый адрес")

        self.status = InvitationStatus.ACCEPTED
        self.accepted_at = at
        self.accepted_by = user_id
        self.record_event(
            InvitationAccepted(
                invitation_id=self.id,
                tenant_id=self.tenant_id,
                user_id=user_id,
            )
        )

    def revoke(self) -> None:
        if self.status is InvitationStatus.ACCEPTED:
            raise InvariantViolationError("Принятое приглашение отозвать нельзя")
        if self.status is InvitationStatus.REVOKED:
            return

        self.status = InvitationStatus.REVOKED
        self.record_event(InvitationRevoked(invitation_id=self.id, tenant_id=self.tenant_id))
