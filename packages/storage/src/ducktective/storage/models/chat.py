from datetime import (
    datetime,
)
from typing import (
    Any,
)
from uuid import (
    UUID,
)

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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

from ducktective.core.chat.value_objects import (
    ChatRole,
)
from ducktective.storage.models.base import (
    Base,
)
from ducktective.storage.models.enums import (
    enum_values,
)


class ConversationModel(Base):
    """Разговор о коде одного репозитория."""

    __tablename__ = "conversation"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"))
    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repository.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255), server_default="")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    messages: Mapped[list["MessageModel"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="MessageModel.created_at",
        lazy="selectin",
    )

    attachment: Mapped["ConversationAttachmentModel | None"] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
        uselist=False,
    )

    __table_args__ = (
        Index("ix_conversation_repository_id_updated_at", "repository_id", "updated_at"),
    )


class ConversationAttachmentModel(Base):
    """Документ, приложенный к разговору.

    Отдельной таблицей: текст требований весит десятки килобайт, а список
    разговоров читается на каждом открытии вкладки. Один на разговор —
    уникальностью по `conversation_id` (D-025).
    """

    __tablename__ = "conversation_attachment"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"),
        unique=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    attached_at: Mapped[datetime] = mapped_column(server_default=func.now())

    conversation: Mapped[ConversationModel] = relationship(back_populates="attachment")


class MessageModel(Base):
    """Реплика разговора вместе с тем, что агент спрашивал у кодовой базы.

    Вызовы инструментов лежат рядом с репликой, которая их попросила:
    открытая заново беседа иначе показывает выводы без источников.
    """

    __tablename__ = "message"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversation.id", ondelete="CASCADE"))
    role: Mapped[ChatRole] = mapped_column(
        Enum(ChatRole, name="chat_role", values_callable=enum_values)
    )
    content: Mapped[str] = mapped_column(Text, server_default="")
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tokens_input: Mapped[int] = mapped_column(Integer, server_default="0")
    tokens_output: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    conversation: Mapped[ConversationModel] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_message_conversation_id_created_at", "conversation_id", "created_at"),
    )
