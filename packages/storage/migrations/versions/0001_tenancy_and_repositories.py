"""tenancy and code repositories

Revision ID: 0001
Revises:
Create Date: 2026-07-26
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


revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("create extension if not exists vector")
    op.execute("create extension if not exists pg_trgm")

    op.create_table(
        "tenant",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenant_slug")),
    )

    op.create_table(
        "user_account",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("external_subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_user_account_tenant_id_tenant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_account")),
        sa.UniqueConstraint(
            "tenant_id",
            "external_subject",
            name=op.f("uq_user_account_tenant_id_external_subject"),
        ),
    )

    vcs_provider = postgresql.ENUM(
        "local",
        "github",
        "bitbucket",
        name="vcs_provider",
        create_type=False,
    )
    egress_policy = postgresql.ENUM(
        "local_only",
        "allow_cloud",
        name="egress_policy",
        create_type=False,
    )
    vcs_provider.create(op.get_bind(), checkfirst=True)
    egress_policy.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "repository",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("vcs_provider", vcs_provider, nullable=False),
        sa.Column("remote_url", sa.Text(), nullable=True),
        sa.Column("default_branch", sa.String(length=255), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("egress_policy", egress_policy, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_repository_tenant_id_tenant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repository")),
        sa.UniqueConstraint("tenant_id", "name", name=op.f("uq_repository_tenant_id_name")),
    )
    op.create_index(op.f("ix_repository_tenant_id"), "repository", ["tenant_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_repository_tenant_id"), table_name="repository")
    op.drop_table("repository")
    op.drop_table("user_account")
    op.drop_table("tenant")

    postgresql.ENUM(name="egress_policy").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="vcs_provider").drop(op.get_bind(), checkfirst=True)
