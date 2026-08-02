"""subject of the head commit as the caption of a review run

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-02
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет заголовок головного коммита к прогону.

    Восемь символов хеша не говорят, что за изменение расследуется, и список
    дел приходится читать по ревизиям. Заголовок снимается на момент заведения
    дела и хранится рядом: спрашивать git заново значит зависеть от того, цела
    ли рабочая копия, а подпись дела должна пережить и её.

    Пустой у прогонов по проиндексированным изменениям: сообщения у них ещё нет.
    """
    op.add_column("review_run", sa.Column("head_subject", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("review_run", "head_subject")
