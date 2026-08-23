"""chosen model on a run and a conversation

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-23
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)


revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Записывает выбранную человеком модель и третий уровень политики egress.

    Модель хранится у прогона и у разговора, а не в общей настройке: сравнивать
    находки между собой имеет смысл, только зная, кто их сделал, а настройка
    к моменту сравнения давно другая.

    Значение `allow_training_cloud` заводится отдельно от `allow_cloud`, потому
    что бесплатные тиры не обещают не учиться на запросах, и согласие на это
    должно быть отдельным действием, а не побочным следствием галочки
    «можно облако» (D-028).
    """
    op.execute("alter type egress_policy add value if not exists 'allow_training_cloud'")
    op.add_column("review_run", sa.Column("preferred_model", sa.String(length=64), nullable=True))
    op.add_column("conversation", sa.Column("preferred_model", sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Значение перечисления не убирается: PostgreSQL этого не умеет.

    Репозитории с политикой `allow_training_cloud` при откате нужно вернуть
    к `allow_cloud` вручную — иначе строка ссылается на значение, которого
    в старом коде нет.
    """
    op.drop_column("conversation", "preferred_model")
    op.drop_column("review_run", "preferred_model")
