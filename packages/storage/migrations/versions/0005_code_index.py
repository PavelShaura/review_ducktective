"""code index: snapshots, source files, symbol graph, chunks and embeddings

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-27
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import (
    op,
)
from pgvector.sqlalchemy import (
    Vector,
)
from sqlalchemy.dialects import (
    postgresql,
)


revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 768

SEARCH_VECTOR = sa.Computed("to_tsvector('simple'::regconfig, search_text)", persisted=True)

SNAPSHOT_STATUS = postgresql.ENUM(
    "pending",
    "running",
    "ready",
    "failed",
    name="snapshot_status",
    create_type=False,
)

SYMBOL_KIND = postgresql.ENUM(
    "module",
    "class",
    "function",
    "method",
    "property",
    name="symbol_kind",
    create_type=False,
)

EDGE_KIND = postgresql.ENUM(
    "calls",
    "imports",
    "inherits",
    "decorates",
    "raises",
    "references",
    name="edge_kind",
    create_type=False,
)


def upgrade() -> None:
    SNAPSHOT_STATUS.create(op.get_bind(), checkfirst=True)
    SYMBOL_KIND.create(op.get_bind(), checkfirst=True)
    EDGE_KIND.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "index_snapshot",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("parent_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column("status", SNAPSHOT_STATUS, nullable=False),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_snapshot_id"],
            ["index_snapshot.id"],
            name=op.f("fk_index_snapshot_parent_snapshot_id_index_snapshot"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repository.id"],
            name=op.f("fk_index_snapshot_repository_id_repository"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_index_snapshot")),
    )
    op.create_index(
        op.f("ix_index_snapshot_commit_sha"), "index_snapshot", ["commit_sha"], unique=False
    )
    op.create_index(
        op.f("ix_index_snapshot_repository_id"), "index_snapshot", ["repository_id"], unique=False
    )

    op.create_table(
        "source_file",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("first_seen_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("last_seen_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["first_seen_snapshot_id"],
            ["index_snapshot.id"],
            name=op.f("fk_source_file_first_seen_snapshot_id_index_snapshot"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_snapshot_id"],
            ["index_snapshot.id"],
            name=op.f("fk_source_file_last_seen_snapshot_id_index_snapshot"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repository.id"],
            name=op.f("fk_source_file_repository_id_repository"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_file")),
        sa.UniqueConstraint(
            "repository_id", "path", name=op.f("uq_source_file_repository_id_path")
        ),
    )
    op.create_index(
        op.f("ix_source_file_repository_id"), "source_file", ["repository_id"], unique=False
    )

    op.create_table(
        "code_symbol",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("parent_symbol_id", sa.Uuid(), nullable=True),
        sa.Column("kind", SYMBOL_KIND, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("qualified_name", sa.Text(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("docstring", sa.Text(), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("start_byte", sa.Integer(), nullable=False),
        sa.Column("end_byte", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), SEARCH_VECTOR, nullable=True),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["source_file.id"],
            name=op.f("fk_code_symbol_file_id_source_file"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_symbol_id"],
            ["code_symbol.id"],
            name=op.f("fk_code_symbol_parent_symbol_id_code_symbol"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repository.id"],
            name=op.f("fk_code_symbol_repository_id_repository"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_symbol")),
        sa.UniqueConstraint(
            "repository_id",
            "qualified_name",
            "start_line",
            name=op.f("uq_code_symbol_repository_id_qualified_name_start_line"),
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index(op.f("ix_code_symbol_file_id"), "code_symbol", ["file_id"], unique=False)
    op.create_index(
        op.f("ix_code_symbol_repository_id"), "code_symbol", ["repository_id"], unique=False
    )
    op.create_index(
        "ix_code_symbol_search_vector",
        "code_symbol",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_code_symbol_qualified_name_trgm",
        "code_symbol",
        ["qualified_name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"qualified_name": "gin_trgm_ops"},
    )

    op.create_table(
        "symbol_edge",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("source_symbol_id", sa.Uuid(), nullable=False),
        sa.Column("target_symbol_id", sa.Uuid(), nullable=True),
        sa.Column("target_qualified_name", sa.Text(), nullable=True),
        sa.Column("kind", EDGE_KIND, nullable=False),
        sa.Column("is_resolved", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repository.id"],
            name=op.f("fk_symbol_edge_repository_id_repository"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_symbol_id"],
            ["code_symbol.id"],
            name=op.f("fk_symbol_edge_source_symbol_id_code_symbol"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_symbol_id"],
            ["code_symbol.id"],
            name=op.f("fk_symbol_edge_target_symbol_id_code_symbol"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_symbol_edge")),
    )
    op.create_index(
        "ix_symbol_edge_incoming",
        "symbol_edge",
        ["repository_id", "target_symbol_id", "kind"],
        unique=False,
    )
    op.create_index(
        "ix_symbol_edge_outgoing",
        "symbol_edge",
        ["repository_id", "source_symbol_id", "kind"],
        unique=False,
    )
    op.create_index(
        "ix_symbol_edge_pending",
        "symbol_edge",
        ["repository_id", "target_qualified_name"],
        unique=False,
    )

    op.create_table(
        "code_chunk",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("symbol_id", sa.Uuid(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("breadcrumb", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), SEARCH_VECTOR, nullable=True),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["source_file.id"],
            name=op.f("fk_code_chunk_file_id_source_file"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repository.id"],
            name=op.f("fk_code_chunk_repository_id_repository"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["symbol_id"],
            ["code_symbol.id"],
            name=op.f("fk_code_chunk_symbol_id_code_symbol"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_chunk")),
    )
    op.create_index(op.f("ix_code_chunk_file_id"), "code_chunk", ["file_id"], unique=False)
    op.create_index(
        "ix_code_chunk_repository_id_content_hash",
        "code_chunk",
        ["repository_id", "content_hash"],
        unique=False,
    )
    op.create_index(
        "ix_code_chunk_search_vector",
        "code_chunk",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )

    op.create_table(
        "embedding_model",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embedding_model")),
        sa.UniqueConstraint("name", name=op.f("uq_embedding_model_name")),
    )

    op.create_table(
        "chunk_embedding",
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_model_id", sa.Uuid(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["code_chunk.id"],
            name=op.f("fk_chunk_embedding_chunk_id_code_chunk"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_model_id"],
            ["embedding_model.id"],
            name=op.f("fk_chunk_embedding_embedding_model_id_embedding_model"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("chunk_id", "embedding_model_id", name=op.f("pk_chunk_embedding")),
    )
    op.create_index(
        "ix_chunk_embedding_vector",
        "chunk_embedding",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chunk_embedding_vector",
        table_name="chunk_embedding",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("chunk_embedding")
    op.drop_table("embedding_model")

    op.drop_index("ix_code_chunk_search_vector", table_name="code_chunk", postgresql_using="gin")
    op.drop_index("ix_code_chunk_repository_id_content_hash", table_name="code_chunk")
    op.drop_index(op.f("ix_code_chunk_file_id"), table_name="code_chunk")
    op.drop_table("code_chunk")

    op.drop_index("ix_symbol_edge_pending", table_name="symbol_edge")
    op.drop_index("ix_symbol_edge_outgoing", table_name="symbol_edge")
    op.drop_index("ix_symbol_edge_incoming", table_name="symbol_edge")
    op.drop_table("symbol_edge")

    op.drop_index(
        "ix_code_symbol_qualified_name_trgm",
        table_name="code_symbol",
        postgresql_using="gin",
        postgresql_ops={"qualified_name": "gin_trgm_ops"},
    )
    op.drop_index("ix_code_symbol_search_vector", table_name="code_symbol", postgresql_using="gin")
    op.drop_index(op.f("ix_code_symbol_repository_id"), table_name="code_symbol")
    op.drop_index(op.f("ix_code_symbol_file_id"), table_name="code_symbol")
    op.drop_table("code_symbol")

    op.drop_index(op.f("ix_source_file_repository_id"), table_name="source_file")
    op.drop_table("source_file")

    op.drop_index(op.f("ix_index_snapshot_repository_id"), table_name="index_snapshot")
    op.drop_index(op.f("ix_index_snapshot_commit_sha"), table_name="index_snapshot")
    op.drop_table("index_snapshot")

    EDGE_KIND.drop(op.get_bind(), checkfirst=True)
    SYMBOL_KIND.drop(op.get_bind(), checkfirst=True)
    SNAPSHOT_STATUS.drop(op.get_bind(), checkfirst=True)
