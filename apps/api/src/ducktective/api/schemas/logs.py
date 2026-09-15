from typing import (
    Any,
)

from pydantic import (
    BaseModel,
)

from ducktective.observability.logfile import (
    LogRecord,
    LogTail,
)


class LogRecordResponse(BaseModel):
    timestamp: str | None
    level: str | None
    logger: str | None
    event: str
    exception: str | None
    fields: dict[str, Any]

    @classmethod
    def from_record(cls, record: LogRecord) -> "LogRecordResponse":
        return cls(
            timestamp=record.timestamp,
            level=record.level,
            logger=record.logger,
            event=record.event,
            exception=record.exception,
            fields=record.fields,
        )


class LogTailResponse(BaseModel):
    """Хвост журнала и то, насколько ему можно верить.

    `skipped_lines` показывается рядом с записями: если в файл писал кто-то
    ещё или он повреждён, администратор увидит это, а не пустое место.
    """

    file: str
    size_bytes: int
    scanned_lines: int
    skipped_lines: int
    truncated: bool
    records: list[LogRecordResponse]

    @classmethod
    def from_tail(cls, file: str, tail: LogTail) -> "LogTailResponse":
        return cls(
            file=file,
            size_bytes=tail.size_bytes,
            scanned_lines=tail.scanned_lines,
            skipped_lines=tail.skipped_lines,
            truncated=tail.truncated,
            records=[LogRecordResponse.from_record(record) for record in tail.records],
        )
