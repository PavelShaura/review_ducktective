from datetime import (
    datetime,
)
from uuid import (
    UUID,
)

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import (
    ARRAY,
    JSONB,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from ducktective.storage.models.base import (
    Base,
)


class PromptVersionModel(Base):
    """Версия промпта, зафиксированная по содержимому.

    Версия — это хеш текста, а не номер: промпт живёт файлом в репозитории,
    и любое его изменение обязано порождать новую запись, иначе утверждение
    «эта версия дала такую precision» нечем подтвердить.
    """

    __tablename__ = "prompt_version"
    __table_args__ = (UniqueConstraint("name", "content_hash"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    content_hash: Mapped[str] = mapped_column(String(64))
    template: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class EvalDatasetModel(Base):
    __tablename__ = "eval_dataset"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class EvalCaseModel(Base):
    """Случай с заранее известным ответом.

    Патч хранится целиком: набор должен воспроизводиться сам по себе, без
    доступа к репозиторию, из которого он когда-то был взят.
    """

    __tablename__ = "eval_case"
    __table_args__ = (UniqueConstraint("dataset_id", "name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("eval_dataset.id", ondelete="CASCADE"),
    )
    name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(Text)
    patch: Mapped[str] = mapped_column(Text)
    expected: Mapped[dict[str, object]] = mapped_column(JSONB)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)


class EvalRunModel(Base):
    __tablename__ = "eval_run"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("eval_dataset.id", ondelete="CASCADE"),
        index=True,
    )
    prompt_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prompt_version.id", ondelete="SET NULL"),
        nullable=True,
    )
    label: Mapped[str] = mapped_column(String(128))
    model: Mapped[str] = mapped_column(String(128))
    config: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    metrics: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class EvalResultModel(Base):
    __tablename__ = "eval_result"
    __table_args__ = (UniqueConstraint("eval_run_id", "eval_case_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    eval_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("eval_run.id", ondelete="CASCADE"),
    )
    eval_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("eval_case.id", ondelete="CASCADE"),
    )
    found_expected: Mapped[bool] = mapped_column(Boolean)
    findings_total: Mapped[int] = mapped_column(Integer)
    raw: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
