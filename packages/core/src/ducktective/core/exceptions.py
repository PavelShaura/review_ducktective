class DomainError(Exception):
    """Базовая ошибка домена."""


class InvariantViolationError(DomainError):
    """Операция нарушила бы инвариант агрегата."""


class VcsOperationError(DomainError):
    """Операция с системой контроля версий завершилась неуспешно."""


class RepositoryPathError(VcsOperationError):
    """Каталог репозитория недоступен.

    Отделён от остальных ошибок git, чтобы недоступный путь не выглядел
    как отсутствующая ревизия.
    """


class DiffParsingError(DomainError):
    """Патч не удалось разобрать."""


class LlmInvocationError(DomainError):
    """Обращение к языковой модели завершилось неуспешно.

    Имя модели лежит полем, а не только в тексте сообщения: прогон
    отчитывается о том, кто именно отказал, и доставать это обратно
    разбором готовой фразы значит хранить структуру в прозе.
    """

    def __init__(self, message: str, *, model: str | None = None) -> None:
        super().__init__(message)
        self.model = model


class LlmContextOverflowError(LlmInvocationError):
    """Промпт не поместился в окно контекста модели.

    Отделена от прочих ошибок вызова, потому что повторять такой запрос
    бессмысленно: он упрётся в то же окно. Чинится настройкой модели или
    сокращением промпта, поэтому размеры выносятся в текст ошибки.
    """


class LlmTimeoutError(LlmInvocationError):
    """Модель не ответила за отведённое время."""


class LlmRateLimitError(LlmInvocationError):
    """Провайдер ограничил частоту обращений."""


class LlmUnavailableError(LlmInvocationError):
    """Провайдер не отвечает или отказал.

    Отделена от таймаута и ограничения частоты: те чинятся настройкой,
    а эта — разбирательством с самим сервисом.
    """


class LlmOutputError(DomainError):
    """Модель вернула ответ, который не удалось разобрать."""

    def __init__(self, message: str, *, model: str | None = None) -> None:
        super().__init__(message)
        self.model = model


class LlmOutputTruncatedError(LlmOutputError):
    """Ответ оборван на лимите выхода, а не сбит с формата.

    Разница видна только по finish_reason и чинится по-разному: лимитом
    и окном модели против уточняющего повтора.
    """


class EntityNotFoundError(DomainError):
    def __init__(self, entity_type: str, entity_id: object) -> None:
        super().__init__(f"{entity_type} не найден: {entity_id}")
        self.entity_type = entity_type
        self.entity_id = entity_id
