"""total duration of a review run across all of its attempts

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-04
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет накопленное время расследования.

    Счётчик на карточке дела считался от последнего старта и после каждого
    продолжения начинался с нуля. Человек же спрашивает, сколько идёт дело,
    а не сколько идёт последний заход, — тем более что продолжение
    переиспользует прежнюю работу, и её время часть цены дела.

    «Расследовать заново» обнуляет счётчик: там прежняя работа выброшена
    вместе с сохранённым ходом.
    """
    op.add_column(
        "review_run",
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("review_run", "duration_ms")
