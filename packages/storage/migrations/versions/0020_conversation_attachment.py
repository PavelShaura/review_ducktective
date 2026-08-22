"""document attached to a conversation

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-22
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Заводит документ, приложенный к разговору.

    Своя таблица, а не поле в `conversation`: текст требований весит десятки
    килобайт, а список разговоров читается на каждом открытии вкладки —
    и тащить с ним содержимое всех приложенных файлов незачем.

    Один документ на разговор держится уникальностью по `conversation_id`
    (D-025). Ограничение в схеме, а не только в домене: правило про один
    документ определяет и то, как читается таблица — строкой, а не списком.

    Текст лежит как есть, без разбиения: куски отбираются под вопрос
    и живут ровно столько, сколько идёт ответ. Хранить их отдельно значило
    бы хранить нарезку, которая устареет с первым же уточнением вопроса.
    """
    op.create_table(
        "conversation_attachment",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversation.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "attached_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("conversation_attachment")
