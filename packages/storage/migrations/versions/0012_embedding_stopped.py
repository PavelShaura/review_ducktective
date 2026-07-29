"""a stop request for the vector pass that follows a ready snapshot

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-30
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет просьбу прекратить досчёт векторов.

    Снапшот помечается готовым до векторов: символы и граф полезны сами по
    себе, и недоступность модели их не обнуляет. Из этого следует, что
    у индексации две завершающие точки, а отмена умела прерывать только
    первую — вторую нельзя было остановить ничем, кроме снятия воркера.

    Отдельный признак, а не статус: снапшот на этом этапе действительно
    завершён, и менять его состояние было бы неправдой.
    """
    op.add_column(
        "index_snapshot",
        sa.Column("embedding_stopped", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("index_snapshot", "embedding_stopped")
