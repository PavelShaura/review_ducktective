from datetime import (
    datetime,
)
from uuid import (
    UUID,
)

from sqlalchemy import (
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from ducktective.core.code_repository.value_objects import (
    EgressPolicy,
    VcsProvider,
)
from ducktective.storage.models.base import (
    Base,
)
from ducktective.storage.models.enums import (
    enum_values,
)


class CodeRepositoryModel(Base):
    __tablename__ = "repository"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    vcs_provider: Mapped[VcsProvider] = mapped_column(
        Enum(
            VcsProvider,
            name="vcs_provider",
            values_callable=enum_values,
        )
    )
    remote_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_branch: Mapped[str] = mapped_column(String(255), default="main")
    local_path: Mapped[str] = mapped_column(Text)
    egress_policy: Mapped[EgressPolicy] = mapped_column(
        Enum(
            EgressPolicy,
            name="egress_policy",
            values_callable=enum_values,
        )
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
