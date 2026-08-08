"""investigation steps of an agentic review run

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-08
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


STEP_KINDS = ("thought", "tool_call", "tool_result", "answer", "fallback")


def upgrade() -> None:
    """Заводит ход расследования: что агент подумал, что вызвал, что получил.

    Отдельная таблица, а не `review_run.config`: результатов инструментов
    на прогон набирается десятками, каждый до двух тысяч символов, и класть
    их в поле агрегата значило бы читать всю трассу при каждом обращении
    к делу.

    Шаги живут вне агрегата прогона и пишутся по ходу работы, короткими
    транзакциями между обращениями к модели: конвейер работает минутами,
    и держать транзакцию открытой всё это время нельзя (D-016).

    Ключ — счётчик, а не UUID: лента дочитывается запросом «что появилось
    после такого-то шага», и курсор для этого должен быть монотонным.
    Порядок по идентификатору совпадает с порядком записи, чего UUID
    не обещает.
    """
    op.create_table(
        "investigation_step",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("review_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(*STEP_KINDS, name="investigation_step_kind"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(length=64), nullable=True),
        sa.Column("arguments", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_error", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_investigation_step_run_id_id",
        "investigation_step",
        ["run_id", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_investigation_step_run_id_id", table_name="investigation_step")
    op.drop_table("investigation_step")
    sa.Enum(name="investigation_step_kind").drop(op.get_bind(), checkfirst=True)
