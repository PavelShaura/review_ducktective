"""terminal stage of an indexing run: vectors are done

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-12
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет этап `complete` и закрывает им завершённые досчёты.

    Готовый снапшот на этапе `embedding` без остановки и без причины отказа
    считается досчитанным: другого признака конца досчёта до этой миграции
    не было. Накатывать при остановленном воркере индексации — идущий досчёт
    иначе будет закрыт раньше времени.
    """
    with op.get_context().autocommit_block():
        op.execute("alter type snapshot_stage add value if not exists 'complete'")

    _for_each_tenant(
        "update index_snapshot set stage = 'complete' "
        "where status = 'ready' and stage = 'embedding' "
        "and embedding_stopped = false and failure_reason is null"
    )


def downgrade() -> None:
    _for_each_tenant("update index_snapshot set stage = 'embedding' where stage = 'complete'")


def _for_each_tenant(statement: str) -> None:
    """Выполняет обновление под каждым тенантом: политика строк иначе не покажет ни строки."""
    connection = op.get_bind()
    tenants = connection.execute(sa.text("select id from tenant")).scalars().all()
    for tenant_id in tenants:
        connection.execute(
            sa.text("select set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        connection.execute(sa.text(statement))
    connection.execute(sa.text("select set_config('app.tenant_id', '', true)"))
