import json
import os
from collections.abc import (
    Iterator,
)
from dataclasses import (
    dataclass,
    field,
)
from pathlib import (
    Path,
)
from typing import (
    Any,
)


LEVEL_ORDER = ("debug", "info", "warning", "error", "critical")
"""Уровни по возрастанию: фильтр «не ниже warning» отсекает всё левее."""

CHUNK_SIZE = 64 * 1024
"""Файл читается с конца такими кусками: последние строки лежат в хвосте,
и ради них не нужно поднимать в память журнал за неделю."""

MAX_LIMIT = 1000


@dataclass(frozen=True, slots=True)
class LogRecord:
    """Одна строка журнала, разобранная на то, что показывает интерфейс.

    Остальные поля записи — контекст события: идентификатор прогона, модель,
    длительность — уходят в `fields` как есть. Их набор у каждого события свой,
    и заранее перечислить их нельзя.
    """

    timestamp: str | None
    level: str | None
    logger: str | None
    event: str
    exception: str | None
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LogQuery:
    """Что показать из хвоста журнала.

    `min_level` — нижняя граница уровня; `logger` — префикс имени логгера,
    так отбирается один сервис (`ducktective.reviewer`) или одна библиотека;
    `text` — подстрока без учёта регистра по всей строке, а не по одному
    полю: искомое может лежать и в событии, и в контексте.
    """

    limit: int = 200
    min_level: str | None = None
    logger: str | None = None
    text: str | None = None


@dataclass(frozen=True, slots=True)
class LogTail:
    records: list[LogRecord]
    """В хронологическом порядке: последняя запись — последняя в списке."""
    size_bytes: int
    scanned_lines: int
    skipped_lines: int
    """Строки, не разобранные как JSON: журнал повреждён или в него писал кто-то
    ещё. Они не показываются, но считаются — молчание скрыло бы поломку."""
    truncated: bool
    """Отбор остановлен по лимиту: раньше в файле есть ещё подходящие записи."""


def tail_records(path: Path, query: LogQuery) -> LogTail:
    """Последние записи журнала, подходящие под запрос.

    Файл читается с конца и разбор прекращается, как только набран лимит:
    хвост нужен целиком лишь тогда, когда фильтр отсеивает почти всё.
    """
    limit = max(1, min(query.limit, MAX_LIMIT))
    min_rank = LEVEL_ORDER.index(query.min_level) if query.min_level else None
    needle = query.text.lower() if query.text else None

    matched: list[LogRecord] = []
    scanned = 0
    skipped = 0
    truncated = False

    for line in _lines_from_end(path):
        if not line.strip():
            continue
        scanned += 1
        record = _parse(line)
        if record is None:
            skipped += 1
            continue
        if min_rank is not None and _rank(record.level) < min_rank:
            continue
        if query.logger and not (record.logger or "").startswith(query.logger):
            continue
        if needle is not None and needle not in line.lower():
            continue
        matched.append(record)
        if len(matched) == limit:
            truncated = True
            break

    matched.reverse()
    return LogTail(
        records=matched,
        size_bytes=path.stat().st_size,
        scanned_lines=scanned,
        skipped_lines=skipped,
        truncated=truncated,
    )


def _parse(line: str) -> LogRecord | None:
    try:
        payload = json.loads(line)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None

    fields: dict[str, Any] = dict(payload)
    return LogRecord(
        timestamp=_text_or_none(fields.pop("timestamp", None)),
        level=_text_or_none(fields.pop("level", None)),
        logger=_text_or_none(fields.pop("logger", None)),
        event=str(fields.pop("event", "")),
        exception=_text_or_none(fields.pop("exception", None)),
        fields=fields,
    )


def _text_or_none(value: object) -> str | None:
    return None if value is None else str(value)


def _rank(level: str | None) -> int:
    """Неизвестный уровень ниже любого известного: фильтр по уровню его прячет,
    а без фильтра он виден — так запись не пропадает совсем."""
    if level is None:
        return -1
    try:
        return LEVEL_ORDER.index(level.lower())
    except ValueError:
        return -1


def _lines_from_end(path: Path) -> Iterator[str]:
    """Строки файла от последней к первой.

    Читается кусками с конца; неполная первая строка куска доклеивается к
    следующему, поэтому граница куска внутри записи не рвёт её пополам.
    """
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        remainder = b""

        while position > 0:
            size = min(CHUNK_SIZE, position)
            position -= size
            handle.seek(position)
            chunk = handle.read(size) + remainder
            lines = chunk.split(b"\n")
            remainder = lines[0]
            for raw in reversed(lines[1:]):
                yield raw.decode("utf-8", errors="replace")

        if remainder:
            yield remainder.decode("utf-8", errors="replace")
