"""human feedback on findings

Revision ID: 0004
Revises: 0003
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


revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FEEDBACK_VERDICT = postgresql.ENUM(
    "useful",
    "false_positive",
    "wontfix",
    name="feedback_verdict",
    create_type=False,
)


def upgrade() -> None:
    FEEDBACK_VERDICT.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "finding_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("verdict", FEEDBACK_VERDICT, nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["finding.id"],
            name=op.f("fk_finding_feedback_finding_id_finding"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name=op.f("fk_finding_feedback_user_id_user_account"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding_feedback")),
    )
    op.create_index(op.f("ix_finding_feedback_finding_id"), "finding_feedback", ["finding_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_finding_feedback_finding_id"), table_name="finding_feedback")
    op.drop_table("finding_feedback")
    postgresql.ENUM(name="feedback_verdict").drop(op.get_bind(), checkfirst=True)
