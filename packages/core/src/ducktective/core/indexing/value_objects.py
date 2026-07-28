from enum import (
    StrEnum,
)


class SnapshotStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SnapshotStage(StrEnum):
    """Чем занята индексация прямо сейчас.

    Разбор файлов — лишь первая часть работы, и обычно не самая долгая:
    на крупном репозитории запись символов и построение графа занимают
    больше. Без явного этапа шкала доходит до конца и замирает, а человеку
    кажется, что всё зависло.
    """

    PARSING = "parsing"
    STORING = "storing"
    LINKING = "linking"
    EMBEDDING = "embedding"


STAGE_TITLES = {
    SnapshotStage.PARSING: "разбираю файлы",
    SnapshotStage.STORING: "сохраняю символы и фрагменты",
    SnapshotStage.LINKING: "строю граф связей",
    SnapshotStage.EMBEDDING: "считаю векторы",
}


class SymbolKind(StrEnum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    PROPERTY = "property"


class EdgeKind(StrEnum):
    """Вид связи между символами.

    Полнота недостижима: в динамическом языке часть вызовов существует только
    во время выполнения. Неразрешённое ребро сохраняется вместе с именем,
    которое не удалось привязать, — для поиска оно всё равно полезно.
    """

    CALLS = "calls"
    IMPORTS = "imports"
    INHERITS = "inherits"
    DECORATES = "decorates"
    RAISES = "raises"
    REFERENCES = "references"


TERMINAL_SNAPSHOT_STATUSES = frozenset(
    {SnapshotStatus.READY, SnapshotStatus.FAILED, SnapshotStatus.CANCELLED}
)
