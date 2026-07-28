"""current stage of an indexing run and the cancelled status

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-28
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STAGE_VALUES = ("parsing", "storing", "linking", "embedding")


def upgrade() -> None:
    """Добавляет этап работы и возможность отмены.

    Разбор файлов заканчивается задолго до конца индексации, а дальше идут
    запись символов и построение графа. Без явного этапа шкала упирается
    в сто процентов и замирает — со стороны это неотличимо от зависания.
    """
    op.execute("alter type snapshot_status add value if not exists 'cancelled'")

    stage = sa.Enum(*STAGE_VALUES, name="snapshot_stage")
    stage.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "index_snapshot",
        sa.Column("stage", stage, nullable=False, server_default="parsing"),
    )


def downgrade() -> None:
    op.drop_column("index_snapshot", "stage")
    sa.Enum(name="snapshot_stage").drop(op.get_bind(), checkfirst=True)
