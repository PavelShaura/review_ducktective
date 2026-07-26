from enum import (
    Enum,
)


def enum_values(enum_class: type[Enum]) -> list[str]:
    """Значения для PG-типа: в БД хранится value, а не имя члена перечисления."""
    return [str(member.value) for member in enum_class]
