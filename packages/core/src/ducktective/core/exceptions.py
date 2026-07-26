class DomainError(Exception):
    """Базовая ошибка домена."""


class InvariantViolationError(DomainError):
    """Операция нарушила бы инвариант агрегата."""


class VcsOperationError(DomainError):
    """Операция с системой контроля версий завершилась неуспешно."""


class DiffParsingError(DomainError):
    """Патч не удалось разобрать."""


class LlmInvocationError(DomainError):
    """Обращение к языковой модели завершилось неуспешно."""


class LlmOutputError(DomainError):
    """Модель вернула ответ, который не удалось разобрать."""


class EntityNotFoundError(DomainError):
    def __init__(self, entity_type: str, entity_id: object) -> None:
        super().__init__(f"{entity_type} не найден: {entity_id}")
        self.entity_type = entity_type
        self.entity_id = entity_id
