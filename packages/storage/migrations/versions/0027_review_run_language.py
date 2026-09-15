"""language the findings of a run are written in

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-16
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LANGUAGE = sa.Enum("ru", "en", name="review_language")


def upgrade() -> None:
    """Прогоны, заведённые раньше, писались по-русски — им и достаётся `ru`."""
    LANGUAGE.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "review_run",
        sa.Column("language", LANGUAGE, nullable=False, server_default="ru"),
    )


def downgrade() -> None:
    op.drop_column("review_run", "language")
    LANGUAGE.drop(op.get_bind(), checkfirst=True)
