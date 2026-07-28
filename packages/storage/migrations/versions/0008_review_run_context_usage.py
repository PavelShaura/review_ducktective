"""how many files of a run were reviewed with index context

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-28
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет счётчик файлов, проревьюенных вместе с окружением.

    Ревью без индекса работает по одному диффу и находит заметно меньше.
    Число нужно, чтобы разница в качестве не выглядела случайностью: по
    завершённому прогону должно быть видно, участвовал ли индекс.
    """
    op.add_column(
        "review_run",
        sa.Column("files_with_context", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("review_run", "files_with_context")
