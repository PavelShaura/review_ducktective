"""indexes on foreign keys that participate in deletion

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-29
"""

from collections.abc import (
    Sequence,
)

from alembic import (
    op,
)


revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = (
    ("ix_code_chunk_symbol_id", "code_chunk", "symbol_id"),
    ("ix_code_symbol_parent_symbol_id", "code_symbol", "parent_symbol_id"),
    ("ix_source_file_first_seen_snapshot_id", "source_file", "first_seen_snapshot_id"),
    ("ix_source_file_last_seen_snapshot_id", "source_file", "last_seen_snapshot_id"),
    ("ix_index_snapshot_parent_snapshot_id", "index_snapshot", "parent_snapshot_id"),
    ("ix_review_run_created_by", "review_run", "created_by"),
    ("ix_finding_feedback_user_id", "finding_feedback", "user_id"),
    ("ix_eval_run_prompt_version_id", "eval_run", "prompt_version_id"),
    ("ix_symbol_edge_source_symbol_id", "symbol_edge", "source_symbol_id"),
    ("ix_symbol_edge_target_symbol_id", "symbol_edge", "target_symbol_id"),
    ("ix_chunk_embedding_embedding_model_id", "chunk_embedding", "embedding_model_id"),
    ("ix_eval_result_eval_case_id", "eval_result", "eval_case_id"),
)


def upgrade() -> None:
    """Индексирует внешние ключи, по которым идёт каскад при удалении.

    Postgres не создаёт индекс на ссылающуюся сторону сам, а при удалении
    родителя обязан найти всех детей. Без индекса это последовательный скан
    на каждую удаляемую строку: на репозитории в семь тысяч файлов это
    сорок тысяч символов против сорока тысяч фрагментов, и удаление
    уходило в минуты, упираясь в процессор.

    `SET NULL` обходится ровно так же дорого, как `CASCADE`: разница в том,
    что делают с найденной строкой, а искать её приходится одинаково.

    Составной индекс не считается покрытием, если колонка стоит в нём
    не первой: `ix_symbol_edge_outgoing` начинается с `repository_id`
    и для запроса `where source_symbol_id = ?` бесполезен. Именно это
    держало 68 секунд из 76 — на каждый удаляемый символ шёл проход
    по всей таблице рёбер.
    """
    for name, table, column in INDEXES:
        op.create_index(name, table, [column])


def downgrade() -> None:
    for name, table, _ in INDEXES:
        op.drop_index(name, table_name=table)
