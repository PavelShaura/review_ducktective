"""conversations about an indexed repository

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-22
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CHAT_ROLES = ("user", "assistant", "tool")


def upgrade() -> None:
    """Заводит разговор о кодовой базе и его реплики.

    Репозиторий у разговора один и не меняется: сменить его посреди беседы
    значит оставить историю, которая говорит о чужом коде, — и агент будет
    отвечать по ней, не подозревая подмены.

    Роль `tool` хранится наравне с вопросом и ответом: то, что агент посмотрел
    в кодовой базе, — часть его хода мысли, и без этих реплик открытая заново
    беседа показывает выводы без источников. По той же причине вызовы лежат
    в самой реплике, а не в отдельной таблице: они читаются только вместе
    с ней и всегда целиком.

    Расход токенов пишется на реплику, а не на разговор: беседа живёт долго,
    модель за это время может смениться, и сумма по разговору перестанет
    отвечать на вопрос, во что обошёлся конкретный ответ.
    """
    op.create_table(
        "conversation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            sa.Uuid(),
            sa.ForeignKey("repository.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_conversation_repository_id_updated_at",
        "conversation",
        ["repository_id", "updated_at"],
    )

    op.create_table(
        "message",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversation.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Enum(*CHAT_ROLES, name="chat_role"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_calls", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("tool_call_id", sa.String(length=128), nullable=True),
        sa.Column("tool_name", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_message_conversation_id_created_at",
        "message",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_message_conversation_id_created_at", table_name="message")
    op.drop_table("message")
    op.drop_index("ix_conversation_repository_id_updated_at", table_name="conversation")
    op.drop_table("conversation")
    sa.Enum(name="chat_role").drop(op.get_bind(), checkfirst=True)
