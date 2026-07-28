"""indexable last segment of the edge target name

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-28
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TARGET_NAME = sa.Computed("regexp_replace(target_qualified_name, '^.*\\.', '')", persisted=True)


def upgrade() -> None:
    """Выносит последний сегмент имени цели в отдельную колонку с индексом.

    Разрешение имён сопоставляет ребро с символом по этому сегменту. Пока он
    вычислялся прямо в запросе, соединение шло перебором: на репозитории
    в семь тысяч файлов это сто тысяч рёбер против семнадцати тысяч имён
    и десятки минут работы. С индексом сравнение идёт по равенству.
    """
    op.add_column(
        "symbol_edge",
        sa.Column("target_name", sa.Text(), TARGET_NAME, nullable=True),
    )
    op.create_index(
        "ix_symbol_edge_target_name",
        "symbol_edge",
        ["repository_id", "target_name"],
        unique=False,
        postgresql_where=sa.text("is_resolved = false"),
    )


def downgrade() -> None:
    op.drop_index("ix_symbol_edge_target_name", table_name="symbol_edge")
    op.drop_column("symbol_edge", "target_name")
