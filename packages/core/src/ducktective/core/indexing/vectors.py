import re


VECTOR_SKIP_PATTERNS: tuple[str, ...] = (
    r"(^|/)migrations/",
    r"(^|/)fixtures?/",
    r"(^|/)node_modules/",
    r"(^|/)static/vendor/",
    r"\.min\.(js|css)$",
    r"\.(po|mo|map|lock|svg)$",
)
"""Пути, чанки которых не получают вектор.

Регулярные выражения POSIX ARE: одинаково читаются `re` и оператором `~`
Postgres. Чанки таких файлов остаются в индексе — граф, чтение строк
и поиск по словам ими пользуются, — но по смыслу не ищутся.
"""

_SKIP = tuple(re.compile(pattern) for pattern in VECTOR_SKIP_PATTERNS)


def deserves_vector(path: str) -> bool:
    return not any(pattern.search(path) for pattern in _SKIP)
