from datetime import (
    datetime,
)
from uuid import (
    UUID,
)

from pgvector.sqlalchemy import (
    Vector,
)
from sqlalchemy import (
    Boolean,
    Computed,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import (
    JSONB,
    TSVECTOR,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from ducktective.core.indexing.value_objects import (
    EdgeKind,
    SnapshotStage,
    SnapshotStatus,
    SymbolKind,
)
from ducktective.storage.models.base import (
    Base,
)
from ducktective.storage.models.enums import (
    enum_values,
)


EMBEDDING_DIMENSIONS = 768
"""Размерность вектора чанка.

pgvector требует фиксировать её на уровне колонки. 768 — наибольшая, которую
поддерживают обе рассматриваемые модели: у `nomic-embed-text-v1.5` она родная,
а `Qwen3-Embedding` режется до неё Matryoshka-усечением без переобучения.
Взять 1024 значило бы закрыть дорогу первой из них.
"""

TARGET_NAME_EXPRESSION = r"regexp_replace(target_qualified_name, '^.*\.', '')"
"""Последний сегмент имени цели ребра.

Считает база, а не приложение: по нему идёт разрешение имён, и вычисление
на лету превращало соединение в перебор — на большом репозитории это
десятки минут вместо секунд.
"""

SEARCH_VECTOR_EXPRESSION = "to_tsvector('simple'::regconfig, search_text)"
"""Вектор считает база, а не приложение: рассинхронизироваться им негде.

Конфигурация `simple` выбрана вместо языковой сознательно — стеммер английского
превращает идентификаторы в неузнаваемые основы, а в коде важны точные имена.
"""


class IndexSnapshotModel(Base):
    __tablename__ = "index_snapshot"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    repository_id: Mapped[UUID] = mapped_column(
        ForeignKey("repository.id", ondelete="CASCADE"),
        index=True,
    )
    parent_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("index_snapshot.id", ondelete="SET NULL"),
        nullable=True,
    )
    commit_sha: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[SnapshotStatus] = mapped_column(
        Enum(SnapshotStatus, name="snapshot_status", values_callable=enum_values)
    )
    stage: Mapped[SnapshotStage] = mapped_column(
        Enum(SnapshotStage, name="snapshot_stage", values_callable=enum_values),
        server_default="parsing",
    )
    stats: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class SourceFileModel(Base):
    __tablename__ = "source_file"
    __table_args__ = (UniqueConstraint("repository_id", "path"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    repository_id: Mapped[UUID] = mapped_column(
        ForeignKey("repository.id", ondelete="CASCADE"),
        index=True,
    )
    path: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    first_seen_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("index_snapshot.id", ondelete="CASCADE")
    )
    last_seen_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("index_snapshot.id", ondelete="CASCADE")
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    symbols: Mapped[list["CodeSymbolModel"]] = relationship(
        back_populates="file",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    chunks: Mapped[list["CodeChunkModel"]] = relationship(
        back_populates="file",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CodeSymbolModel(Base):
    """Символ кодовой базы.

    Уникальность имени и строки проверяется отложенно: переиндексация файла —
    это «удалить старые символы, вставить новые», и в середине такой замены
    старые ещё существуют. Инвариант должен выполняться в конце транзакции,
    а не после каждой вставленной строки.
    """

    __tablename__ = "code_symbol"
    __table_args__ = (
        UniqueConstraint(
            "repository_id",
            "qualified_name",
            "start_line",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_code_symbol_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_code_symbol_qualified_name_trgm",
            "qualified_name",
            postgresql_using="gin",
            postgresql_ops={"qualified_name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    repository_id: Mapped[UUID] = mapped_column(
        ForeignKey("repository.id", ondelete="CASCADE"),
        index=True,
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_file.id", ondelete="CASCADE"),
        index=True,
    )
    parent_symbol_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("code_symbol.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[SymbolKind] = mapped_column(
        Enum(SymbolKind, name="symbol_kind", values_callable=enum_values)
    )
    name: Mapped[str] = mapped_column(String(255))
    qualified_name: Mapped[str] = mapped_column(Text)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    docstring: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    start_byte: Mapped[int] = mapped_column(Integer)
    end_byte: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    search_text: Mapped[str] = mapped_column(Text, default="")
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(SEARCH_VECTOR_EXPRESSION, persisted=True),
    )

    file: Mapped[SourceFileModel] = relationship(back_populates="symbols")
    parent: Mapped["CodeSymbolModel | None"] = relationship(
        remote_side="CodeSymbolModel.id",
        lazy="noload",
    )


class SymbolEdgeModel(Base):
    """Ребро графа символов.

    Индексы стоят на обоих направлениях: обход вниз отвечает на вопрос
    «что вызывает изменённый код», обход вверх — «что сломается».

    Связи с символами объявлены отношениями, а не только внешними ключами:
    иначе SQLAlchemy не знает о зависимости и вставляет ребро раньше символа,
    на который оно ссылается.
    """

    __tablename__ = "symbol_edge"
    __table_args__ = (
        Index("ix_symbol_edge_incoming", "repository_id", "target_symbol_id", "kind"),
        Index("ix_symbol_edge_outgoing", "repository_id", "source_symbol_id", "kind"),
        Index("ix_symbol_edge_pending", "repository_id", "target_qualified_name"),
        Index(
            "ix_symbol_edge_target_name",
            "repository_id",
            "target_name",
            postgresql_where=text("is_resolved = false"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repository.id", ondelete="CASCADE"))
    source_symbol_id: Mapped[UUID] = mapped_column(ForeignKey("code_symbol.id", ondelete="CASCADE"))
    target_symbol_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("code_symbol.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_qualified_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_name: Mapped[str | None] = mapped_column(
        Text,
        Computed(TARGET_NAME_EXPRESSION, persisted=True),
        nullable=True,
    )
    kind: Mapped[EdgeKind] = mapped_column(
        Enum(EdgeKind, name="edge_kind", values_callable=enum_values)
    )
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)

    source_symbol: Mapped[CodeSymbolModel] = relationship(
        foreign_keys=[source_symbol_id],
        lazy="noload",
    )
    target_symbol: Mapped[CodeSymbolModel | None] = relationship(
        foreign_keys=[target_symbol_id],
        lazy="noload",
    )


class CodeChunkModel(Base):
    __tablename__ = "code_chunk"
    __table_args__ = (
        Index("ix_code_chunk_repository_id_content_hash", "repository_id", "content_hash"),
        Index("ix_code_chunk_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repository.id", ondelete="CASCADE"))
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_file.id", ondelete="CASCADE"),
        index=True,
    )
    symbol_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("code_symbol.id", ondelete="SET NULL"),
        nullable=True,
    )
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    token_count: Mapped[int] = mapped_column(Integer)
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    breadcrumb: Mapped[str] = mapped_column(Text)
    search_text: Mapped[str] = mapped_column(Text, default="")
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(SEARCH_VECTOR_EXPRESSION, persisted=True),
    )

    file: Mapped[SourceFileModel] = relationship(back_populates="chunks")
    symbol: Mapped[CodeSymbolModel | None] = relationship(lazy="noload")


class EmbeddingModelModel(Base):
    __tablename__ = "embedding_model"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    dimensions: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ChunkEmbeddingModel(Base):
    """Вектор чанка.

    Эмбеддинги отделены от чанков, чтобы при переезде на другую модель
    держать два набора параллельно и сравнить их на одном индексе.
    """

    __tablename__ = "chunk_embedding"
    __table_args__ = (
        Index(
            "ix_chunk_embedding_vector",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("code_chunk.id", ondelete="CASCADE"),
        primary_key=True,
    )
    embedding_model_id: Mapped[UUID] = mapped_column(
        ForeignKey("embedding_model.id", ondelete="CASCADE"),
        primary_key=True,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
