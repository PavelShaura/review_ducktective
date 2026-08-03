"""per-node degradation marks in review_run.config

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-03
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)
from sqlalchemy.dialects import (
    postgresql,
)


revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет настройки прогона, куда пишутся отметки о деградации.

    До сих пор о сбое было известно одно предложение на весь прогон:
    `failure_reason` не говорит, какой узел упал и на каком файле. С одним
    ревьюером это ещё читалось, с четырьмя — нет: файл, потерянный одним
    из них, и файл, не прочитанный никем, выглядят одинаково.

    Колонка названа `config`, а не `degradations`, потому что по
    `03-data-model.md` сюда же встанут выбранные ревьюеры и модели прогона.
    Отметки лежат под своим ключом.
    """
    op.add_column(
        "review_run",
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("review_run", "config")
