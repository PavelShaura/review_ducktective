"""models configured by an organization

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-24
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


revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Заводит модели, которые организация настраивает сама (D-029).

    Ключ провайдера лежит шифротекстом: секрет шифрования живёт в окружении,
    и выгрузка базы без него не даёт ничего. Открытым текстом строка пережила
    бы резервную копию и чужой доступ к тому.

    Уникальность по паре «организация и имя»: имя — то, чем модель называют
    при запуске прогона, и два разных «free» в одном списке сделали бы выбор
    неразличимым.
    """
    model_trust = postgresql.ENUM(
        "local",
        "private_remote",
        "training_remote",
        name="model_trust",
        create_type=False,
    )
    model_trust.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "model_profile",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("base_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("trust", model_trust, nullable=False),
        sa.Column("supports_tools", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("context_window", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_model_profile_tenant_id_tenant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_profile")),
        sa.UniqueConstraint("tenant_id", "name", name=op.f("uq_model_profile_tenant_id_name")),
    )
    op.create_index(op.f("ix_model_profile_tenant_id"), "model_profile", ["tenant_id"])

    op.execute("alter table model_profile enable row level security")
    op.execute("alter table model_profile force row level security")
    op.execute(
        "create policy tenant_isolation on model_profile "
        "using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) "
        "with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("drop policy if exists tenant_isolation on model_profile")
    op.drop_index(op.f("ix_model_profile_tenant_id"), table_name="model_profile")
    op.drop_table("model_profile")
    op.execute("drop type if exists model_trust")
