"""symbol name is unique within its file, not across the repository

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-21
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REPOSITORY_WIDE = "uq_code_symbol_repository_id_qualified_name_start_line"
PER_FILE = "uq_code_symbol_repository_id_file_id_qualified_name_start_line"

DROP_LATER_TWINS = """
delete from code_symbol
where id in (
    select id
    from (
        select
            symbol.id,
            first_value(symbol.id) over (
                partition by symbol.repository_id, symbol.qualified_name, symbol.start_line
                order by file.path
            ) as keeper
        from code_symbol as symbol
        join source_file as file on file.id = symbol.file_id
    ) as ranked
    where id <> keeper
)
"""


def upgrade() -> None:
    """Имя символа уникально в пределах файла: два файла с одним путём
    модуля оба попадают в индекс."""
    op.drop_constraint(REPOSITORY_WIDE, "code_symbol", type_="unique")
    op.create_unique_constraint(
        PER_FILE,
        "code_symbol",
        ["repository_id", "file_id", "qualified_name", "start_line"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    """Из файлов с одним именем модуля в старой схеме умещается один:
    символы остальных удаляются, порядок — по пути файла."""
    _for_each_tenant(DROP_LATER_TWINS)
    op.drop_constraint(PER_FILE, "code_symbol", type_="unique")
    op.create_unique_constraint(
        REPOSITORY_WIDE,
        "code_symbol",
        ["repository_id", "qualified_name", "start_line"],
        deferrable=True,
        initially="DEFERRED",
    )


def _for_each_tenant(statement: str) -> None:
    """Выполняет удаление под каждым тенантом: политика строк иначе не покажет ни строки."""
    connection = op.get_bind()
    tenants = connection.execute(sa.text("select id from tenant")).scalars().all()
    for tenant_id in tenants:
        connection.execute(
            sa.text("select set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        connection.execute(sa.text(statement))
    connection.execute(sa.text("select set_config('app.tenant_id', '', true)"))
