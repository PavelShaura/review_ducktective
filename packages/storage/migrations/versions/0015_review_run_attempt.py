"""attempt number so a stale run can tell it is no longer the current one

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-04
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет номер попытки расследования.

    Работающий прогон узнавал о прекращении по статусу дела, а «продолжить»
    переводит прекращённое дело обратно в очередь. Прежняя попытка спрашивала
    «меня прекратили?», получала «нет» и работала дальше: на одном деле
    оказывались два прогона, они занимали воркер, писали в один сохранённый
    ход и оба звали модель.

    Номер растёт при каждом возвращении в очередь, и попытка сверяется
    с ним, а не со статусом.
    """
    op.add_column(
        "review_run",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )


def downgrade() -> None:
    op.drop_column("review_run", "attempt")
