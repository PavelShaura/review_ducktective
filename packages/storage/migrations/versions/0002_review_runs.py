"""review runs, files, hunks and findings

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-26
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


revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_DEFINITIONS = {
    "review_source": ("pull_request", "local_diff", "upload"),
    "review_status": ("queued", "indexing", "running", "completed", "failed", "cancelled"),
    "change_type": ("added", "modified", "deleted", "renamed"),
    "diff_side": ("old", "new"),
    "severity": ("critical", "major", "minor", "nitpick"),
    "finding_category": (
        "correctness",
        "security",
        "performance",
        "style",
        "tests",
        "architecture",
    ),
    "finding_status": ("proposed", "verified", "rejected", "published"),
    "finding_producer": ("llm", "static_analyzer"),
    "evidence_kind": ("retrieved_chunk", "quoted_code", "tool_output"),
}


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUM_DEFINITIONS[name], name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for name in ENUM_DEFINITIONS:
        _enum(name).create(bind, checkfirst=True)

    op.create_table(
        "review_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("source", _enum("review_source"), nullable=False),
        sa.Column("external_pull_request_id", sa.String(length=255), nullable=True),
        sa.Column("base_sha", sa.String(length=64), nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column("status", _enum("review_status"), nullable=False),
        sa.Column("totals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_review_run_tenant_id_tenant"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repository.id"],
            name=op.f("fk_review_run_repository_id_repository"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user_account.id"],
            name=op.f("fk_review_run_created_by_user_account"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_run")),
    )
    op.create_index(op.f("ix_review_run_tenant_id"), "review_run", ["tenant_id"])
    op.create_index(op.f("ix_review_run_repository_id"), "review_run", ["repository_id"])

    op.create_table(
        "review_file",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("previous_path", sa.Text(), nullable=True),
        sa.Column("change_type", _enum("change_type"), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("added_lines", sa.Integer(), nullable=False),
        sa.Column("removed_lines", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["review_run.id"],
            name=op.f("fk_review_file_run_id_review_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_file")),
    )
    op.create_index(op.f("ix_review_file_run_id"), "review_file", ["run_id"])

    op.create_table(
        "review_hunk",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_file_id", sa.Uuid(), nullable=False),
        sa.Column("old_start", sa.Integer(), nullable=False),
        sa.Column("old_lines", sa.Integer(), nullable=False),
        sa.Column("new_start", sa.Integer(), nullable=False),
        sa.Column("new_lines", sa.Integer(), nullable=False),
        sa.Column("header", sa.Text(), nullable=False),
        sa.Column("patch_text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["review_file_id"],
            ["review_file.id"],
            name=op.f("fk_review_hunk_review_file_id_review_file"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_hunk")),
    )
    op.create_index(op.f("ix_review_hunk_review_file_id"), "review_hunk", ["review_file_id"])

    op.create_table(
        "finding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=False),
        sa.Column("line_end", sa.Integer(), nullable=False),
        sa.Column("side", _enum("diff_side"), nullable=False),
        sa.Column("severity", _enum("severity"), nullable=False),
        sa.Column("category", _enum("finding_category"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("suggested_patch", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("producer", _enum("finding_producer"), nullable=False),
        sa.Column("producer_name", sa.String(length=64), nullable=False),
        sa.Column("rule_id", sa.String(length=128), nullable=True),
        sa.Column("status", _enum("finding_status"), nullable=False),
        sa.Column("dedup_key", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["review_run.id"],
            name=op.f("fk_finding_run_id_review_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding")),
        sa.UniqueConstraint("run_id", "dedup_key", name=op.f("uq_finding_run_id_dedup_key")),
    )
    op.create_index(op.f("ix_finding_run_id"), "finding", ["run_id"])

    op.create_table(
        "finding_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("kind", _enum("evidence_kind"), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["finding.id"],
            name=op.f("fk_finding_evidence_finding_id_finding"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding_evidence")),
    )
    op.create_index(op.f("ix_finding_evidence_finding_id"), "finding_evidence", ["finding_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_finding_evidence_finding_id"), table_name="finding_evidence")
    op.drop_table("finding_evidence")
    op.drop_index(op.f("ix_finding_run_id"), table_name="finding")
    op.drop_table("finding")
    op.drop_index(op.f("ix_review_hunk_review_file_id"), table_name="review_hunk")
    op.drop_table("review_hunk")
    op.drop_index(op.f("ix_review_file_run_id"), table_name="review_file")
    op.drop_table("review_file")
    op.drop_index(op.f("ix_review_run_repository_id"), table_name="review_run")
    op.drop_index(op.f("ix_review_run_tenant_id"), table_name="review_run")
    op.drop_table("review_run")

    bind = op.get_bind()
    for name in ENUM_DEFINITIONS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
