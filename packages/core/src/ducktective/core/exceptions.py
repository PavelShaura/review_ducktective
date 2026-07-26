class DomainError(Exception):
    """Базовая ошибка домена."""


class InvariantViolationError(DomainError):
    """Операция нарушила бы инвариант агрегата."""


class EntityNotFoundError(DomainError):
    def __init__(self, entity_type: str, entity_id: object) -> None:
        super().__init__(f"{entity_type} не найден: {entity_id}")
        self.entity_type = entity_type
        self.entity_id = entity_id
