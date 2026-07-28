"""prompt versions, llm calls and evaluation runs

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-28
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


revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_version",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_version")),
        sa.UniqueConstraint(
            "name",
            "content_hash",
            name=op.f("uq_prompt_version_name_content_hash"),
        ),
    )

    op.create_table(
        "eval_dataset",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_dataset")),
        sa.UniqueConstraint("name", name=op.f("uq_eval_dataset_name")),
    )

    op.create_table(
        "eval_case",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("patch", sa.Text(), nullable=False),
        sa.Column("expected", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["eval_dataset.id"],
            name=op.f("fk_eval_case_dataset_id_eval_dataset"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_case")),
        sa.UniqueConstraint("dataset_id", "name", name=op.f("uq_eval_case_dataset_id_name")),
    )

    op.create_table(
        "eval_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version_id", sa.Uuid(), nullable=True),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["eval_dataset.id"],
            name=op.f("fk_eval_run_dataset_id_eval_dataset"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["prompt_version.id"],
            name=op.f("fk_eval_run_prompt_version_id_prompt_version"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_run")),
    )
    op.create_index(op.f("ix_eval_run_dataset_id"), "eval_run", ["dataset_id"], unique=False)

    op.create_table(
        "eval_result",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("eval_run_id", sa.Uuid(), nullable=False),
        sa.Column("eval_case_id", sa.Uuid(), nullable=False),
        sa.Column("found_expected", sa.Boolean(), nullable=False),
        sa.Column("findings_total", sa.Integer(), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["eval_case_id"],
            ["eval_case.id"],
            name=op.f("fk_eval_result_eval_case_id_eval_case"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["eval_run_id"],
            ["eval_run.id"],
            name=op.f("fk_eval_result_eval_run_id_eval_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_result")),
        sa.UniqueConstraint(
            "eval_run_id",
            "eval_case_id",
            name=op.f("uq_eval_result_eval_run_id_eval_case_id"),
        ),
    )


def downgrade() -> None:
    op.drop_table("eval_result")
    op.drop_index(op.f("ix_eval_run_dataset_id"), table_name="eval_run")
    op.drop_table("eval_run")
    op.drop_table("eval_case")
    op.drop_table("eval_dataset")
    op.drop_table("prompt_version")
