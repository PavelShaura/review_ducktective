"""embedding backend chosen for a repository

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-12
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "repository",
        sa.Column("embedding_backend", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("repository", "embedding_backend")
