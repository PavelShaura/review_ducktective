import io
import json
import logging
from pathlib import (
    Path,
)

from ducktective.observability.logging import (
    FOREIGN_CONFIGURED_LOGGERS,
    HANDLER_NAME,
    SELF_HANDLED_LOGGERS,
    configure_logging,
    get_logger,
)


class CapturingHandler(logging.Handler):
    """Всё, что дошло до корневого логгера."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record.getMessage())


def _json_lines(text: str) -> list[dict[str, object]]:
    """Каждая непустая строка обязана быть отдельным JSON-объектом."""
    parsed: list[dict[str, object]] = []
    for line in text.splitlines():
        if line:
            parsed.append(json.loads(line))
    return parsed


def test_library_with_its_own_handler_does_not_write_twice() -> None:
    """LiteLLM печатает строку сама и пропускает её же в корневой логгер.

    В логе прогона тогда каждое обращение к модели видно дважды: раз
    в формате библиотеки, раз в нашем.
    """
    configure_logging()
    captured = CapturingHandler()
    logging.getLogger().addHandler(captured)

    try:
        for name in SELF_HANDLED_LOGGERS:
            logging.getLogger(name).warning("LiteLLM completion() model= gemma")
    finally:
        logging.getLogger().removeHandler(captured)

    assert captured.records == []


def test_records_of_other_libraries_still_reach_the_common_stream() -> None:
    """Глушится дубль, а не чужие логи: alembic и arq пишут в общий поток."""
    configure_logging()
    captured = CapturingHandler()
    logging.getLogger().addHandler(captured)

    try:
        logging.getLogger("arq.worker").warning("job failed")
    finally:
        logging.getLogger().removeHandler(captured)

    assert captured.records == ["job failed"]


def test_stdlib_record_with_traceback_is_one_json_line() -> None:
    """Запись стандартного logging в JSON-режиме — такой же объект, как у structlog.

    Раньше она уходила текстом, а traceback растягивался на несколько строк:
    поток переставал быть JSON Lines, и сборщик логов спотыкался на нём.
    """
    stream = io.StringIO()
    configure_logging(json_output=True, stream=stream)

    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("arq.worker").exception("job %s failed", "abc")

    (record,) = _json_lines(stream.getvalue())
    assert record["event"] == "job abc failed"
    assert record["logger"] == "arq.worker"
    assert record["level"] == "error"
    assert "ValueError: boom" in str(record["exception"])


def test_structlog_record_carries_logger_name() -> None:
    """По имени логгера видно, какое приложение написало строку в общий файл."""
    stream = io.StringIO()
    configure_logging(json_output=True, stream=stream)

    get_logger("ducktective.reviewer").info("reviewer.started", profile="dev")

    (record,) = _json_lines(stream.getvalue())
    assert record["event"] == "reviewer.started"
    assert record["logger"] == "ducktective.reviewer"
    assert record["profile"] == "dev"


def test_file_receives_json_lines_while_console_stays_readable(tmp_path: Path) -> None:
    """Файл — JSON Lines при любом формате экрана, и с подставленными аргументами.

    Форматтер structlog подставляет аргументы в сообщение и обнуляет их на
    самой записи: второй обработчик получал бы шаблон с `%s` вместо текста.
    """
    stream = io.StringIO()
    log_file = tmp_path / "logs" / "ducktective.jsonl"
    configure_logging(json_output=False, stream=stream, file=log_file)

    logging.getLogger("arq.worker").info("job %s took %.1fs", "abc", 1.5)

    (record,) = _json_lines(log_file.read_text(encoding="utf-8"))
    assert record["event"] == "job abc took 1.5s"
    assert "job abc took 1.5s" in stream.getvalue()
    assert not stream.getvalue().lstrip().startswith("{")


def test_foreign_handlers_are_detached_so_lines_are_not_doubled() -> None:
    """arq из CLI вешает свой обработчик, uvicorn глушит распространение.

    В первом случае каждая строка выходит дважды, во втором — минует наш
    формат. После настройки записи этих библиотек идут только через корень.
    """
    for name in FOREIGN_CONFIGURED_LOGGERS:
        foreign = logging.getLogger(name)
        foreign.addHandler(logging.StreamHandler(io.StringIO()))
        foreign.propagate = False

    stream = io.StringIO()
    configure_logging(json_output=True, stream=stream)

    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1", "GET", "/", "1.1", 200
    )
    logging.getLogger("arq").info("Starting worker")

    for name in FOREIGN_CONFIGURED_LOGGERS:
        assert logging.getLogger(name).handlers == []
        assert logging.getLogger(name).propagate
    events = [record["event"] for record in _json_lines(stream.getvalue())]
    assert events == ['127.0.0.1 - "GET / HTTP/1.1" 200', "Starting worker"]


def test_reconfiguration_replaces_own_handlers_only() -> None:
    """Повторная настройка не копит обработчики и не трогает чужие.

    API настраивает логи в lifespan, тесты — в каждом прогоне; без замены
    каждая строка выходила бы столько раз, сколько раз вызвана настройка.
    pytest на время теста вешает на корень свой обработчик — он остаётся.
    """
    first = io.StringIO()
    configure_logging(json_output=True, stream=first)
    captured = CapturingHandler()
    logging.getLogger().addHandler(captured)

    second = io.StringIO()
    try:
        configure_logging(json_output=True, stream=second)
        logging.getLogger("arq.worker").info("once")
    finally:
        logging.getLogger().removeHandler(captured)

    own = [h for h in logging.getLogger().handlers if h.name == HANDLER_NAME]
    assert len(own) == 1
    assert first.getvalue() == ""
    assert [record["event"] for record in _json_lines(second.getvalue())] == ["once"]
    assert captured.records == ["once"]
