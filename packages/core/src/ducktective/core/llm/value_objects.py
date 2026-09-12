from dataclasses import (
    dataclass,
    field,
)
from enum import (
    StrEnum,
)
from typing import (
    Any,
)

from ducktective.core.code_repository.value_objects import (
    ModelTrust,
)


class LlmRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, kw_only=True)
class ToolSpec:
    """Инструмент, предложенный модели.

    Схема параметров — JSON Schema словарём: это формат протокола, одинаковый
    у всех провайдеров, и переводить его в доменные типы значило бы переводить
    обратно на границе клиента.
    """

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class ToolCall:
    """Запрос модели на вызов инструмента.

    Аргументы остаются сырым текстом, каким их вернула модель: разобрать их
    может не получиться, и тогда ответом должна стать ошибка в результате
    вызова, а не исключение. Модель, увидев такую ошибку, повторяет вызов;
    упавший цикл этого шанса не даёт.
    """

    id: str
    name: str
    arguments: str


@dataclass(frozen=True, kw_only=True)
class LlmMessage:
    role: LlmRole
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    """Вызовы, о которых попросила модель. Заполняется только у ассистента."""

    tool_call_id: str | None = None
    """Вызов, на который отвечает это сообщение. Обязателен у роли `tool`."""


@dataclass(frozen=True, kw_only=True)
class ModelRequirements:
    """Требования узла к модели.

    Роутер выбирает провайдера по этим требованиям и политике репозитория:
    при запрете облака дешёвая локальная модель используется даже там, где
    качество будет ниже.
    """

    needs_deep_reasoning: bool = False
    needs_tool_calling: bool = False
    """Узел ведёт диалог с вызовами инструментов, а не спрашивает одним разом."""

    min_context_tokens: int = 0
    """Окно, меньше которого узлу работать негде.

    Требование узла, а не прогона: одноразовый проход укладывается в то, что
    есть, а цикл с инструментами копит диалог — каждый результат остаётся
    в нём до конца, — и на модели, где прохода хватало, упирается в потолок
    на втором вызове. Ноль означает «сколько дадут»: у моделей за чужими
    серверами окно неизвестно, и выдумывать за них его нельзя.
    """

    allowed_trust: ModelTrust = ModelTrust.LOCAL
    """Предельный уровень доверия, разрешённый политикой репозитория.

    Пришёл на смену признаку «можно облако»: разница между провайдером,
    обещавшим не хранить запросы, и бесплатным маршрутом, который на них
    учится, — это в точности та разница, ради которой политика заведена
    (D-028).
    """

    preferred_model: str | None = None
    """Модель, выбранная человеком при запуске прогона или разговора.

    Пожелание, а не приказ: названная модель используется, если проходит
    и по политике репозитория, и по требованиям узла. Не прошедшая молча
    уступает место подходящей — файл без ревью хуже файла, проверенного
    не той моделью.
    """

    max_output_tokens: int = 4096
    temperature: float = 0.0

    session_key: str = ""
    """Разговор, к которому относятся обращения: прогон ревью или беседа.

    Нужен провайдерам, которые по нему маршрутизируют и кэшируют промпт
    между шагами одного диалога и отказывают запросам без него. Пустой
    означает разовое обращение, у которого продолжения не будет.
    """

    @property
    def cloud_allowed(self) -> bool:
        return self.allowed_trust is not ModelTrust.LOCAL


@dataclass(frozen=True, kw_only=True)
class LlmUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True, kw_only=True)
class LlmResponse:
    content: str
    model: str
    provider: str
    usage: LlmUsage = field(default_factory=LlmUsage)
    latency_ms: int = 0
    is_cache_hit: bool = False
    is_truncated: bool = False
    """Модель упёрлась в лимит выходных токенов, и ответ оборван на полуслове."""

    context_window: int = 0
    """Окно ответившей модели в токенах, ноль — неизвестно.

    Модель выбирает роутер, поэтому окно сообщается ответом. Цикл
    с инструментами по нему задаёт предел результата и момент остановки.
    """

    tool_calls: tuple[ToolCall, ...] = ()

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass(frozen=True, kw_only=True)
class LlmStreamPiece:
    """Кусок ответа, пришедший до того, как ответ дописан.

    Приращения текста идут по мере генерации, а итог приходит последним
    и единственный раз: только к концу становится известно, попросила ли
    модель инструменты и во сколько токенов обошёлся ответ.

    Одним типом вместо двух, потому что поток один: разделять их значит
    заставлять вызывающего разбирать объединение на каждом куске.
    """

    text: str = ""
    response: LlmResponse | None = None
    notice: str = ""
    """Событие, о котором надо сказать человеку до того, как пойдёт текст.

    Пока такое одно: ответ отдан другой модели, потому что первая отказала.
    Подменить исполнителя молча нельзя — человек выбирал модель сам и вправе
    знать, чей ответ он читает.
    """

    @property
    def is_final(self) -> bool:
        return self.response is not None
