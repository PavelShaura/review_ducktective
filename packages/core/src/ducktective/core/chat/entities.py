from dataclasses import (
    dataclass,
    field,
)
from datetime import (
    UTC,
    datetime,
)
from typing import (
    Self,
)
from uuid import (
    uuid4,
)

from ducktective.core.aggregate import (
    AggregateRoot,
)
from ducktective.core.chat.events import (
    ConversationStarted,
)
from ducktective.core.chat.value_objects import (
    ChatRole,
    ChatUsage,
    ToolInvocation,
)
from ducktective.core.exceptions import (
    InvariantViolationError,
)
from ducktective.core.types import (
    ConversationId,
    MessageId,
    RepositoryId,
    TenantId,
)


MAX_DOCUMENT_CHARS = 400_000
"""Насколько большой документ принимается.

Предел не про окно — в окно документ и не поедет, из него достаются куски, —
а про здравый смысл: четыреста тысяч знаков это книга, и человек, приложивший
её вместо страницы требований, ошибся файлом.
"""

MAX_TITLE_LENGTH = 80
MAX_QUESTION_LENGTH = 4000
"""Насколько длинным бывает вопрос.

Предел не про базу, а про окно: вопрос идёт в диалог целиком и вместе
с историей и результатами инструментов делит с ними то же место. Файл,
вставленный в поле ввода, съел бы его весь и не оставил ничего на ответ.
"""


@dataclass(kw_only=True)
class ChatMessage:
    """Реплика разговора.

    Вызовы инструментов живут в самой реплике, а не рядом: то, что агент
    спросил у кодовой базы, — часть его хода мысли, и отделять их значит
    показывать выводы без источников.
    """

    id: MessageId
    role: ChatRole
    content: str
    created_at: datetime
    tool_calls: tuple[ToolInvocation, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None
    model: str | None = None
    usage: ChatUsage = field(default_factory=ChatUsage)

    @property
    def is_answer(self) -> bool:
        return self.role is ChatRole.ASSISTANT and bool(self.content)


@dataclass(kw_only=True)
class AttachedDocument:
    """Документ, приложенный к разговору.

    Живёт в агрегате разговора, а не рядом: он читается вместе с ним и
    только с ним, и разговор без него — другой разговор, потому что
    отвечать агент будет иначе.
    """

    name: str
    text: str
    attached_at: datetime

    @property
    def size(self) -> int:
        return len(self.text)


@dataclass(kw_only=True)
class Conversation(AggregateRoot):
    """Разговор о коде одного репозитория.

    Репозиторий выбирается один раз и не меняется: сменить его посреди
    беседы значит оставить историю, которая говорит о чужом коде, — и агент
    будет отвечать по ней, не подозревая подмены.
    """

    id: ConversationId
    tenant_id: TenantId
    repository_id: RepositoryId
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessage] = field(default_factory=list)
    document: AttachedDocument | None = None
    preferred_model: str | None = None
    """Модель, выбранная для этого разговора.

    Пожелание, а не приказ: приложенный документ всё равно оставляет
    разговор локальным (D-025), и удалённая модель в этом случае молча
    уступает место локальной.
    """

    @classmethod
    def start(
        cls,
        *,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        title: str = "",
        preferred_model: str | None = None,
    ) -> Self:
        now = datetime.now(UTC)
        conversation = cls(
            id=ConversationId(uuid4()),
            tenant_id=tenant_id,
            repository_id=repository_id,
            title=title[:MAX_TITLE_LENGTH],
            created_at=now,
            updated_at=now,
            preferred_model=preferred_model,
        )
        conversation.record_event(
            ConversationStarted(
                conversation_id=conversation.id,
                tenant_id=tenant_id,
                repository_id=repository_id,
            )
        )
        return conversation

    def attach(self, name: str, text: str) -> AttachedDocument:
        """Прикладывает документ к разговору, заменяя прежний.

        Документ один (D-025): с двумя сразу нужен выбор, в каком из них
        искать, и инструмент перестаёт быть однозначным раньше, чем доказана
        польза самого замысла.
        """
        body = text.strip()
        if not body:
            raise InvariantViolationError("Документ пустой")
        if len(body) > MAX_DOCUMENT_CHARS:
            raise InvariantViolationError(
                f"Документ длиннее {MAX_DOCUMENT_CHARS} символов: похоже, приложен не тот файл"
            )

        self.document = AttachedDocument(
            name=name.strip()[:MAX_TITLE_LENGTH] or "документ",
            text=body,
            attached_at=datetime.now(UTC),
        )
        self.updated_at = self.document.attached_at
        return self.document

    def detach(self) -> None:
        self.document = None
        self.updated_at = datetime.now(UTC)

    @property
    def has_document(self) -> bool:
        return self.document is not None

    def ask(self, question: str) -> ChatMessage:
        """Записывает вопрос человека.

        Вопрос сохраняется до обращения к модели: ответ может не случиться —
        модель недоступна, окно кончилось, — и разговор, потерявший вопрос,
        выглядит так, будто его не задавали.
        """
        text = question.strip()
        if not text:
            raise InvariantViolationError("Вопрос пустой")
        if len(text) > MAX_QUESTION_LENGTH:
            raise InvariantViolationError(
                f"Вопрос длиннее {MAX_QUESTION_LENGTH} символов: он не оставит места ответу"
            )

        message = self._append(ChatRole.USER, text)
        if not self.title:
            self.title = text[:MAX_TITLE_LENGTH]
        return message

    def record_tool_call(self, invocations: tuple[ToolInvocation, ...]) -> ChatMessage:
        """Отмечает, что агент решил посмотреть в кодовую базу."""
        return self._append(ChatRole.ASSISTANT, "", tool_calls=invocations)

    def record_tool_result(self, invocation: ToolInvocation, result: str) -> ChatMessage:
        return self._append(
            ChatRole.TOOL,
            result,
            tool_call_id=invocation.call_id,
            tool_name=invocation.name,
        )

    def record_answer(
        self,
        content: str,
        *,
        model: str | None = None,
        usage: ChatUsage | None = None,
    ) -> ChatMessage:
        return self._append(ChatRole.ASSISTANT, content, model=model, usage=usage)

    @property
    def last_question(self) -> str:
        for message in reversed(self.messages):
            if message.role is ChatRole.USER:
                return message.content
        return ""

    def _append(
        self,
        role: ChatRole,
        content: str,
        *,
        tool_calls: tuple[ToolInvocation, ...] = (),
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        model: str | None = None,
        usage: ChatUsage | None = None,
    ) -> ChatMessage:
        message = ChatMessage(
            id=MessageId(uuid4()),
            role=role,
            content=content,
            created_at=datetime.now(UTC),
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            model=model,
            usage=usage or ChatUsage(),
        )
        self.messages.append(message)
        self.updated_at = message.created_at
        return message
