from datetime import (
    datetime,
)
from uuid import (
    UUID,
)

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import (
    JSONB,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from ducktective.core.tenancy.value_objects import (
    InvitationStatus,
    TenantRole,
)
from ducktective.storage.models.base import (
    Base,
)
from ducktective.storage.models.enums import (
    enum_values,
)


class TenantModel(Base):
    __tablename__ = "tenant"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    settings: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class UserAccountModel(Base):
    __tablename__ = "user_account"
    __table_args__ = (UniqueConstraint("external_issuer", "external_subject"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"))
    external_issuer: Mapped[str] = mapped_column(String(255))
    external_subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[TenantRole] = mapped_column(
        Enum(
            TenantRole,
            name="tenant_role",
            values_callable=enum_values,
        )
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class TenantInvitationModel(Base):
    __tablename__ = "tenant_invitation"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"),
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[TenantRole] = mapped_column(
        Enum(
            TenantRole,
            name="tenant_role",
            values_callable=enum_values,
        )
    )
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[UUID] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[InvitationStatus] = mapped_column(
        Enum(
            InvitationStatus,
            name="invitation_status",
            values_callable=enum_values,
        )
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    accepted_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"),
        nullable=True,
    )
