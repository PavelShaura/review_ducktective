"""token usage and cost on review runs

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-26
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "review_run",
        sa.Column("tokens_input", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "review_run",
        sa.Column("tokens_output", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "review_run",
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("review_run", "cost_usd")
    op.drop_column("review_run", "tokens_output")
    op.drop_column("review_run", "tokens_input")
