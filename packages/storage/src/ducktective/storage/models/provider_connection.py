from datetime import (
    datetime,
)
from uuid import (
    UUID,
)

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
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
)

from ducktective.core.code_repository.value_objects import (
    ModelTrust,
)
from ducktective.storage.models.base import (
    Base,
)
from ducktective.storage.models.enums import (
    enum_values,
)


class ProviderConnectionModel(Base):
    """Доступ организации к провайдеру. Ключ лежит шифротекстом."""

    __tablename__ = "provider_connection"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64))
    default_model: Mapped[str] = mapped_column(String(255))
    catalogue: Mapped[list[str]] = mapped_column(JSONB, default=list)
    catalogue_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(64), default="")
    base_url: Mapped[str] = mapped_column(Text, default="")
    encrypted_api_key: Mapped[str] = mapped_column(Text, default="")
    trust: Mapped[ModelTrust] = mapped_column(
        Enum(ModelTrust, name="model_trust", values_callable=enum_values)
    )
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=True)
    context_window: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
