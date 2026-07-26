from datetime import (
    datetime,
)
from uuid import (
    UUID,
)

from sqlalchemy import (
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import (
    JSONB,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from ducktective.core.diff.value_objects import (
    ChangeType,
    DiffSide,
)
from ducktective.core.review.value_objects import (
    EvidenceKind,
    FeedbackVerdict,
    FindingCategory,
    FindingProducer,
    FindingStatus,
    ReviewSource,
    ReviewStatus,
    Severity,
)
from ducktective.storage.models.base import (
    Base,
)
from ducktective.storage.models.enums import (
    enum_values,
)


class ReviewRunModel(Base):
    __tablename__ = "review_run"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"),
        index=True,
    )
    repository_id: Mapped[UUID] = mapped_column(
        ForeignKey("repository.id", ondelete="CASCADE"),
        index=True,
    )
    source: Mapped[ReviewSource] = mapped_column(
        Enum(ReviewSource, name="review_source", values_callable=enum_values)
    )
    external_pull_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_sha: Mapped[str] = mapped_column(String(64))
    head_sha: Mapped[str] = mapped_column(String(64))
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status", values_callable=enum_values)
    )
    totals: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_input: Mapped[int] = mapped_column(Integer, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    files: Mapped[list["ReviewFileModel"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    findings: Mapped[list["FindingModel"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ReviewFileModel(Base):
    __tablename__ = "review_file"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("review_run.id", ondelete="CASCADE"),
        index=True,
    )
    path: Mapped[str] = mapped_column(Text)
    previous_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_type: Mapped[ChangeType] = mapped_column(
        Enum(ChangeType, name="change_type", values_callable=enum_values)
    )
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    added_lines: Mapped[int] = mapped_column(Integer, default=0)
    removed_lines: Mapped[int] = mapped_column(Integer, default=0)

    run: Mapped[ReviewRunModel] = relationship(back_populates="files")
    hunks: Mapped[list["ReviewHunkModel"]] = relationship(
        back_populates="file",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ReviewHunkModel(Base):
    __tablename__ = "review_hunk"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    review_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("review_file.id", ondelete="CASCADE"),
        index=True,
    )
    old_start: Mapped[int] = mapped_column(Integer)
    old_lines: Mapped[int] = mapped_column(Integer)
    new_start: Mapped[int] = mapped_column(Integer)
    new_lines: Mapped[int] = mapped_column(Integer)
    header: Mapped[str] = mapped_column(Text, default="")
    patch_text: Mapped[str] = mapped_column(Text)

    file: Mapped[ReviewFileModel] = relationship(back_populates="hunks")


class FindingModel(Base):
    __tablename__ = "finding"
    __table_args__ = (UniqueConstraint("run_id", "dedup_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("review_run.id", ondelete="CASCADE"),
        index=True,
    )
    file_path: Mapped[str] = mapped_column(Text)
    line_start: Mapped[int] = mapped_column(Integer)
    line_end: Mapped[int] = mapped_column(Integer)
    side: Mapped[DiffSide] = mapped_column(
        Enum(DiffSide, name="diff_side", values_callable=enum_values)
    )
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="severity", values_callable=enum_values)
    )
    category: Mapped[FindingCategory] = mapped_column(
        Enum(FindingCategory, name="finding_category", values_callable=enum_values)
    )
    title: Mapped[str] = mapped_column(Text)
    body_markdown: Mapped[str] = mapped_column(Text)
    suggested_patch: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    producer: Mapped[FindingProducer] = mapped_column(
        Enum(FindingProducer, name="finding_producer", values_callable=enum_values)
    )
    producer_name: Mapped[str] = mapped_column(String(64))
    rule_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[FindingStatus] = mapped_column(
        Enum(FindingStatus, name="finding_status", values_callable=enum_values)
    )
    dedup_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    run: Mapped[ReviewRunModel] = relationship(back_populates="findings")
    evidence: Mapped[list["FindingEvidenceModel"]] = relationship(
        back_populates="finding",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    feedback: Mapped[list["FindingFeedbackModel"]] = relationship(
        back_populates="finding",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class FindingFeedbackModel(Base):
    __tablename__ = "finding_feedback"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    finding_id: Mapped[UUID] = mapped_column(
        ForeignKey("finding.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"),
        nullable=True,
    )
    verdict: Mapped[FeedbackVerdict] = mapped_column(
        Enum(FeedbackVerdict, name="feedback_verdict", values_callable=enum_values)
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    finding: Mapped["FindingModel"] = relationship(back_populates="feedback")


class FindingEvidenceModel(Base):
    __tablename__ = "finding_evidence"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    finding_id: Mapped[UUID] = mapped_column(
        ForeignKey("finding.id", ondelete="CASCADE"),
        index=True,
    )
    kind: Mapped[EvidenceKind] = mapped_column(
        Enum(EvidenceKind, name="evidence_kind", values_callable=enum_values)
    )
    file_path: Mapped[str] = mapped_column(Text)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snippet: Mapped[str] = mapped_column(Text)

    finding: Mapped[FindingModel] = relationship(back_populates="evidence")
