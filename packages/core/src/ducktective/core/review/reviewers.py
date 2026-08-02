from enum import (
    StrEnum,
)


REVIEWER_NAME_PREFIX = "reviewer:"


class ReviewerKind(StrEnum):
    """Специализация ревьюера — разные глаза на один и тот же дифф.

    Порядок членов задаёт порядок ревьюеров в плане: сначала тот, кто читает
    смысл изменения, затем те, кого зовут по признакам.
    """

    CORRECTNESS = "correctness"
    SECURITY = "security"
    PERFORMANCE = "performance"
    CONVENTIONS = "conventions"


def reviewer_name(kind: ReviewerKind) -> str:
    return f"{REVIEWER_NAME_PREFIX}{kind.value}"


def reviewer_kind_of(name: str) -> ReviewerKind | None:
    """Специализация по имени ревьюера, если домен её знает.

    Незнакомое имя — не ошибка: так выглядят ревьюер-заглушка в тестах
    и одиночный проход в сравнительных прогонах. Политика отбора судит
    по признакам специализации, а незнакомому имени признаков не сопоставлено,
    поэтому ограничивать его она не берётся.
    """
    try:
        return ReviewerKind(name.removeprefix(REVIEWER_NAME_PREFIX))
    except ValueError:
        return None
