"""store first-migration timestamps with time zone

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-27
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


revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAIVE_TABLES = ("tenant", "repository", "user_account")


def upgrade() -> None:
    """Приводит колонки первой миграции к timestamptz.

    Таблицы из `0001` создавались без часового пояса, всё, что появилось
    позже, — с ним. Домен оперирует aware-временем в UTC, и naive-колонка
    рано или поздно даёт ошибку на уровне драйвера.

    Преобразование задано явным `AT TIME ZONE 'UTC'`: без него Postgres
    истолковал бы сохранённое время в часовом поясе сессии и сдвинул его.
    """
    for table in NAIVE_TABLES:
        op.alter_column(
            table,
            "created_at",
            existing_type=postgresql.TIMESTAMP(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=False,
            existing_server_default=sa.text("now()"),
            postgresql_using="created_at at time zone 'UTC'",
        )


def downgrade() -> None:
    for table in NAIVE_TABLES:
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            type_=postgresql.TIMESTAMP(),
            existing_nullable=False,
            existing_server_default=sa.text("now()"),
            postgresql_using="created_at at time zone 'UTC'",
        )
