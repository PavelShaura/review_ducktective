"""organizations, roles and invitations

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-23
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)
from sqlalchemy.dialects import (
    postgresql,
)


revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LEGACY_ISSUER = "legacy"


def upgrade() -> None:
    """Делает участника организации опознаваемым, а приглашение — записью.

    Личность опознаётся парой «издатель и субъект», а не почтой: почту в
    провайдере меняют, и привязка по ней отдала бы учётную запись тому, кто
    занял освободившийся адрес. Уникальность переезжает с пары «тенант и
    субъект» на пару «издатель и субъект»: одна личность состоит в одной
    организации, и войти дважды в разные ей нельзя (D-027).

    Строкам, заведённым до авторизации, издателем ставится `legacy`: они
    появились из настройки, а не из токена, и делать вид, что за ними стоит
    подтверждённая личность, нельзя.

    Секрет приглашения хранится отпечатком: ссылка — способ войти в чужую
    организацию, и держать её в таблице в пригодном к предъявлению виде
    значит хранить готовый ключ.
    """
    tenant_role = postgresql.ENUM(
        "owner",
        "member",
        name="tenant_role",
        create_type=False,
    )
    tenant_role.create(op.get_bind(), checkfirst=True)

    invitation_status = postgresql.ENUM(
        "pending",
        "accepted",
        "revoked",
        name="invitation_status",
        create_type=False,
    )
    invitation_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "user_account",
        sa.Column(
            "external_issuer",
            sa.String(length=255),
            nullable=False,
            server_default=LEGACY_ISSUER,
        ),
    )
    op.alter_column("user_account", "external_issuer", server_default=None)
    op.add_column(
        "user_account",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute("update user_account set role = 'member' where role not in ('owner', 'member')")
    op.alter_column(
        "user_account",
        "role",
        type_=tenant_role,
        existing_type=sa.String(length=32),
        postgresql_using="role::tenant_role",
    )

    op.drop_constraint(
        op.f("uq_user_account_tenant_id_external_subject"),
        "user_account",
        type_="unique",
    )
    op.create_unique_constraint(
        op.f("uq_user_account_external_issuer_external_subject"),
        "user_account",
        ["external_issuer", "external_subject"],
    )
    op.create_index(
        op.f("ix_user_account_tenant_id"),
        "user_account",
        ["tenant_id"],
    )

    op.create_table(
        "tenant_invitation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", tenant_role, nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=False),
        sa.Column("status", invitation_status, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_tenant_invitation_tenant_id_tenant"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["user_account.id"],
            name=op.f("fk_tenant_invitation_invited_by_user_account"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by"],
            ["user_account.id"],
            name=op.f("fk_tenant_invitation_accepted_by_user_account"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_invitation")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_tenant_invitation_token_digest")),
    )
    op.create_index(
        op.f("ix_tenant_invitation_tenant_id"),
        "tenant_invitation",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_tenant_invitation_invited_by"),
        "tenant_invitation",
        ["invited_by"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_tenant_invitation_invited_by"), table_name="tenant_invitation")
    op.drop_index(op.f("ix_tenant_invitation_tenant_id"), table_name="tenant_invitation")
    op.drop_table("tenant_invitation")

    op.drop_index(op.f("ix_user_account_tenant_id"), table_name="user_account")
    op.drop_constraint(
        op.f("uq_user_account_external_issuer_external_subject"),
        "user_account",
        type_="unique",
    )
    op.create_unique_constraint(
        op.f("uq_user_account_tenant_id_external_subject"),
        "user_account",
        ["tenant_id", "external_subject"],
    )
    op.alter_column(
        "user_account",
        "role",
        type_=sa.String(length=32),
        existing_type=postgresql.ENUM(name="tenant_role"),
        postgresql_using="role::text",
    )
    op.drop_column("user_account", "last_seen_at")
    op.drop_column("user_account", "external_issuer")

    op.execute("drop type if exists invitation_status")
    op.execute("drop type if exists tenant_role")
