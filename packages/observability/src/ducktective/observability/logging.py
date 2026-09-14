import copy
import logging
import logging.handlers
import sys
from pathlib import (
    Path,
)
from typing import (
    TextIO,
)

import structlog
from structlog.typing import (
    Processor,
)


SELF_HANDLED_LOGGERS = ("LiteLLM",)
"""Библиотеки, которые вешают свой обработчик и пишут строку сами.

Их записи не пропускаются в корневой логгер: иначе каждая появляется дважды —
раз в их формате, раз в нашем, — и лог прогона состоит из повторов. Глушится
распространение, а не сама библиотека: строка про выбранную модель полезна,
лишним её делает только дубль.
"""

FOREIGN_CONFIGURED_LOGGERS = ("arq", "uvicorn", "uvicorn.error", "uvicorn.access")
"""Библиотеки, которые настраивают свои логгеры сами, минуя наш формат.

`arq` из командной строки вешает на свой логгер текстовый обработчик и
пропускает записи дальше: каждая строка воркера выходит дважды. `uvicorn`
глушит распространение и пишет своим форматом: строки сервера в JSON-выводе
остаются текстом. У них снимаются собственные обработчики, а записи идут в
корневой логгер: формат тогда один на всех, и в отличие от `LiteLLM` здесь
нечего беречь — у этих библиотек нет своей разметки, только другой префикс.
"""

HANDLER_NAME = "ducktective"
"""Имя наших обработчиков на корневом логгере.

По нему повторный вызов `configure_logging` находит и снимает свои прежние
обработчики, не трогая чужие: pytest на время теста вешает на корень свой.
"""


def configure_logging(
    *,
    level: str = "INFO",
    json_output: bool = False,
    stream: TextIO | None = None,
    file: Path | None = None,
) -> None:
    """Настраивает structlog и стандартный logging на единый вывод.

    В разработке удобнее читаемый вывод, в контейнере — JSON для сбора логов.

    Записи стандартного `logging` проходят ту же цепочку процессоров, что и
    записи structlog: иначе строки arq, uvicorn и alembic в JSON-режиме
    остаются текстом, traceback растягивается на несколько строк, и поток
    нельзя разобрать как JSON Lines — каждая строка обязана быть объектом.

    Файл, если задан, получает JSON Lines независимо от формата на экране:
    экран читает человек, файл — grep, jq и сборщик логов. Файл только
    дописывается, ротация остаётся logrotate: несколько процессов пишут в
    один файл, и ротация изнутри любого из них потеряла бы строки остальных.

    Поток вывода выбирается вызывающим, потому что у stdio-транспорта MCP
    stdout занят самим протоколом: строка лога там ломает поток JSON-RPC.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        cache_logger_on_first_use=True,
    )

    handlers: list[logging.Handler] = [
        _StreamSink(stream or sys.stdout),
    ]
    handlers[0].setFormatter(_formatter(shared_processors, json_output=json_output))
    if file is not None:
        file.parent.mkdir(parents=True, exist_ok=True)
        file_sink = _FileSink(file, encoding="utf-8")
        file_sink.setFormatter(_formatter(shared_processors, json_output=True))
        handlers.append(file_sink)

    root = logging.getLogger()
    for previous in list(root.handlers):
        if previous.name == HANDLER_NAME:
            root.removeHandler(previous)
            previous.close()
    for handler in handlers:
        handler.set_name(HANDLER_NAME)
        root.addHandler(handler)
    root.setLevel(numeric_level)

    for name in SELF_HANDLED_LOGGERS:
        logging.getLogger(name).propagate = False

    for name in FOREIGN_CONFIGURED_LOGGERS:
        foreign = logging.getLogger(name)
        for handler in list(foreign.handlers):
            foreign.removeHandler(handler)
        foreign.propagate = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


def _formatter(
    shared_processors: list[Processor],
    *,
    json_output: bool,
) -> logging.Formatter:
    """Форматтер, прогоняющий чужие записи через общую цепочку процессоров.

    Исключение для JSON сворачивается в строку до рендера: JSON Lines не
    терпит переносов внутри записи. Консольный рендер печатает traceback сам,
    поэтому ему исключение отдаётся как есть.
    """
    renderer: Processor = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if json_output
        else structlog.dev.ConsoleRenderer()
    )
    processors: list[Processor] = [structlog.stdlib.ProcessorFormatter.remove_processors_meta]
    if json_output:
        processors.append(structlog.processors.format_exc_info)
    processors.append(renderer)
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=processors,
    )


def _format_copy(handler: logging.Handler, record: logging.LogRecord) -> str:
    """Форматирует копию записи, а не саму запись.

    `ProcessorFormatter` подставляет аргументы в сообщение и обнуляет
    `record.args` прямо на записи. Второй обработчик — файл после экрана —
    получал бы шаблон с `%s` вместо текста.
    """
    return logging.Handler.format(handler, copy.copy(record))


class _StreamSink(logging.StreamHandler[TextIO]):
    def format(self, record: logging.LogRecord) -> str:
        return _format_copy(self, record)


class _FileSink(logging.handlers.WatchedFileHandler):
    """Файл переоткрывается после того, как logrotate его переместил."""

    def format(self, record: logging.LogRecord) -> str:
        return _format_copy(self, record)
