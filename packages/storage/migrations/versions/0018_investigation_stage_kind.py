"""stage steps in the investigation log

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-08
"""

from collections.abc import (
    Sequence,
)

from alembic import (
    op,
)


revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет вид шага «этап» — то, чем прогон занят прямо сейчас.

    Шаги писал только агентный ревьюер, а до него прогон минутами собирает
    окружение и ничего об этом не говорит. Лента в это время пуста, и по ней
    не отличить идущую работу от вставшей.
    """
    op.execute("ALTER TYPE investigation_step_kind ADD VALUE IF NOT EXISTS 'stage'")


def downgrade() -> None:
    """Значение перечисления остаётся.

    PostgreSQL не умеет удалять значение из типа, а пересоздание типа ради
    отката потребовало бы переписать всю таблицу. Лишнее значение никому
    не мешает: шагов такого вида после отката просто не появляется.
    """
