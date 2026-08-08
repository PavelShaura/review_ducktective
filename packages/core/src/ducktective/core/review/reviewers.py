from enum import (
    StrEnum,
)


REVIEWER_NAME_PREFIX = "reviewer:"


class ReviewMode(StrEnum):
    """Чем читается файл.

    Ревьюер один (D-022), но работать он может по-разному: агентно —
    запрашивая у инструментов то, что ему нужно, — либо одним проходом
    по заранее собранному окружению. Второе не наследие, а запасной путь:
    на файле, который вместе с диалогом не помещается в окно, цикл
    не начинается вовсе.
    """

    AGENTIC = "agentic"
    SINGLE_PASS = "single-pass"


def reviewer_name(mode: ReviewMode) -> str:
    return f"{REVIEWER_NAME_PREFIX}{mode.value}"


def review_mode_of(name: str) -> ReviewMode | None:
    """Режим по имени ревьюера, если домен его знает.

    Незнакомое имя — не ошибка: так выглядит ревьюер-заглушка в тестах
    и одиночный проход в сравнительных прогонах. Планировщик такому имени
    режима не сопоставляет и потому его не ограничивает.
    """
    try:
        return ReviewMode(name.removeprefix(REVIEWER_NAME_PREFIX))
    except ValueError:
        return None
