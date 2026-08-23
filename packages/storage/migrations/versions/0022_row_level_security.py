"""row level security for tenant data

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-23
"""

from collections.abc import (
    Sequence,
)

from alembic import (
    op,
)


revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TENANT_MATCH = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
POLICY_NAME = "tenant_isolation"

ROOT_TABLES = ("repository", "review_run", "conversation")
REPOSITORY_SCOPED = (
    "index_snapshot",
    "source_file",
    "code_symbol",
    "symbol_edge",
    "code_chunk",
)
CHILD_TABLES = (
    ("chunk_embedding", "code_chunk", "chunk_id"),
    ("review_file", "review_run", "run_id"),
    ("review_hunk", "review_file", "review_file_id"),
    ("finding", "review_run", "run_id"),
    ("finding_evidence", "finding", "finding_id"),
    ("finding_feedback", "finding", "finding_id"),
    ("investigation_step", "review_run", "run_id"),
    ("message", "conversation", "conversation_id"),
    ("conversation_attachment", "conversation", "conversation_id"),
)


def upgrade() -> None:
    """Закрывает данные тенанта политикой базы, а не только фильтром в коде.

    Условие D-023 «отложить до появления второго тенанта» наступило вместе
    с авторизацией (D-027). Проверки принадлежности в use cases остаются:
    политика ловит забытый фильтр, а доменное правило объясняет отказ.

    Тенант транзакции называет приложение через `app.tenant_id`. Не назвав
    его, транзакция не увидит ни строки: сравнение с пустым значением ложно
    для всех. Это и нужно контуру входа — он работает до того, как членство
    выяснено, и трогает только `tenant`, `user_account` и `tenant_invitation`,
    которые под политику не поставлены: кода в них нет, а читаются они
    по личности, а не по организации.

    Дочерние таблицы спрашивают не про тенанта, а про своего родителя,
    и упираются в его политику. Так знание о том, кому принадлежит находка,
    лежит в одном месте — на прогоне, — а не копируется вниз по дереву.

    `force row level security` включён, потому что владелец таблицы иначе
    политику не замечает, а приложение ходит именно под владельцем схемы.
    Миграции с данными после этого должны называть тенанта сами.
    """
    for table in ROOT_TABLES:
        _enable(table)
        op.execute(
            f"create policy {POLICY_NAME} on {table} "
            f"using ({TENANT_MATCH}) with check ({TENANT_MATCH})"
        )

    for table in REPOSITORY_SCOPED:
        _enable(table)
        condition = f"exists (select 1 from repository r where r.id = {table}.repository_id)"
        op.execute(
            f"create policy {POLICY_NAME} on {table} using ({condition}) with check ({condition})"
        )

    for table, parent, column in CHILD_TABLES:
        _enable(table)
        condition = f"exists (select 1 from {parent} p where p.id = {table}.{column})"
        op.execute(
            f"create policy {POLICY_NAME} on {table} using ({condition}) with check ({condition})"
        )


def downgrade() -> None:
    tables = [table for table, _, _ in CHILD_TABLES] + list(REPOSITORY_SCOPED) + list(ROOT_TABLES)
    for table in tables:
        op.execute(f"drop policy if exists {POLICY_NAME} on {table}")
        op.execute(f"alter table {table} no force row level security")
        op.execute(f"alter table {table} disable row level security")


def _enable(table: str) -> None:
    op.execute(f"alter table {table} enable row level security")
    op.execute(f"alter table {table} force row level security")
