from dataclasses import (
    dataclass,
    field,
)
from enum import (
    StrEnum,
)


class ChatRole(StrEnum):
    """Кто сказал реплику.

    Роль `tool` хранится наравне с остальными: разговор о коде состоит
    не только из вопросов и ответов, но и из того, что агент посмотрел
    в кодовой базе. Без этих реплик открытая заново беседа выглядит как
    обмен утверждениями, у которых нет источника.
    """

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatEventKind(StrEnum):
    """Что произошло по ходу ответа.

    Событие — единица потока: клиент получает их по мере появления и рисует
    разговор до того, как ответ дописан. Разделение по видам нужно ровно
    для этого: приращение текста дописывается в реплику, вызов инструмента
    открывает карточку, а пометка объясняет, чем этот ответ ограничен.
    """

    TOKEN = "token"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    NOTE = "note"
    ANSWER = "answer"
    FAILURE = "failure"


@dataclass(frozen=True, kw_only=True)
class ToolInvocation:
    """Обращение агента к кодовой базе, каким его видит человек."""

    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True, kw_only=True)
class ChatUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def plus(self, other: "ChatUsage") -> "ChatUsage":
        return ChatUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


@dataclass(frozen=True, kw_only=True)
class ChatEvent:
    """Единица потока ответа.

    Поля необязательные, потому что вид события решает, какие из них
    заполнены: у приращения текста есть только текст, у вызова инструмента —
    имя и аргументы, у итога — модель и расход токенов.
    """

    kind: ChatEventKind
    text: str = ""
    tool: ToolInvocation | None = None
    model: str | None = None
    usage: ChatUsage = field(default_factory=ChatUsage)
