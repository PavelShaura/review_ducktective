import json
from collections.abc import (
    Sequence,
)
from pathlib import (
    Path,
)

import pytest

from ducktective.observability import (
    logfile,
)
from ducktective.observability.logfile import (
    LogQuery,
    tail_records,
)


def _write(path: Path, entries: Sequence[dict[str, object] | str]) -> Path:
    lines = [entry if isinstance(entry, str) else json.dumps(entry) for entry in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _entry(index: int, level: str = "info", logger: str = "ducktective.api") -> dict[str, object]:
    return {
        "event": f"event {index}",
        "level": level,
        "logger": logger,
        "timestamp": f"2026-09-15T10:00:{index:02d}Z",
        "run_id": index,
    }


def test_returns_last_records_in_chronological_order(tmp_path: Path) -> None:
    """Хвост читается с конца, но показывается как в файле: последняя запись — внизу."""
    path = _write(tmp_path / "log.jsonl", [_entry(index) for index in range(5)])

    tail = tail_records(path, LogQuery(limit=3))

    assert [record.event for record in tail.records] == ["event 2", "event 3", "event 4"]
    assert tail.truncated
    assert tail.scanned_lines == 3
    assert tail.records[-1].fields == {"run_id": 4}
    assert tail.records[-1].timestamp == "2026-09-15T10:00:04Z"


def test_record_split_by_chunk_boundary_is_not_torn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Граница куска попадает внутрь записи — запись всё равно целая."""
    monkeypatch.setattr(logfile, "CHUNK_SIZE", 50)
    entries = [_entry(index, logger="ducktective.reviewer.worker") for index in range(20)]
    path = _write(tmp_path / "log.jsonl", entries)

    tail = tail_records(path, LogQuery(limit=100))

    assert [record.event for record in tail.records] == [f"event {i}" for i in range(20)]
    assert tail.skipped_lines == 0
    assert not tail.truncated


def test_min_level_hides_lower_and_unknown_levels(tmp_path: Path) -> None:
    """«Не ниже warning» отсекает info и то, у чего уровня нет вовсе."""
    path = _write(
        tmp_path / "log.jsonl",
        [
            _entry(0, level="info"),
            _entry(1, level="warning"),
            {"event": "no level"},
            _entry(3, level="error"),
        ],
    )

    tail = tail_records(path, LogQuery(min_level="warning"))

    assert [record.event for record in tail.records] == ["event 1", "event 3"]


def test_logger_prefix_and_text_filters(tmp_path: Path) -> None:
    """Префикс логгера отбирает один сервис, подстрока ищется по всей строке."""
    path = _write(
        tmp_path / "log.jsonl",
        [
            _entry(0, logger="ducktective.reviewer"),
            _entry(1, logger="ducktective.indexer"),
            _entry(2, logger="arq.worker"),
        ],
    )

    by_logger = tail_records(path, LogQuery(logger="ducktective."))
    assert [record.logger for record in by_logger.records] == [
        "ducktective.reviewer",
        "ducktective.indexer",
    ]

    by_text = tail_records(path, LogQuery(text="INDEXER"))
    assert [record.event for record in by_text.records] == ["event 1"]

    by_field = tail_records(path, LogQuery(text='"run_id": 2'))
    assert [record.event for record in by_field.records] == ["event 2"]


def test_malformed_lines_are_counted_not_shown(tmp_path: Path) -> None:
    """Чужая строка в файле не роняет чтение, но и не прячется молча."""
    path = _write(
        tmp_path / "log.jsonl",
        [_entry(0), "12:00:01 plain text from someone else", "[1, 2, 3]", _entry(3)],
    )

    tail = tail_records(path, LogQuery())

    assert [record.event for record in tail.records] == ["event 0", "event 3"]
    assert tail.skipped_lines == 2
    assert tail.scanned_lines == 4


def test_exception_is_separated_from_fields(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "log.jsonl",
        [{"event": "job failed", "level": "error", "exception": "Traceback...\nValueError"}],
    )

    (record,) = tail_records(path, LogQuery()).records

    assert record.exception == "Traceback...\nValueError"
    assert record.fields == {}
    assert record.logger is None


def test_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    path.write_text("", encoding="utf-8")

    tail = tail_records(path, LogQuery())

    assert tail.records == []
    assert tail.size_bytes == 0
