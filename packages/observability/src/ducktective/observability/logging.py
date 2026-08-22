import logging
import sys
from typing import (
    Any,
    TextIO,
)

import structlog


SELF_HANDLED_LOGGERS = ("LiteLLM",)
"""Библиотеки, которые вешают свой обработчик и пишут строку сами.

Их записи не пропускаются в корневой логгер: иначе каждая появляется дважды —
раз в их формате, раз в нашем, — и лог прогона состоит из повторов. Глушится
распространение, а не сама библиотека: строка про выбранную модель полезна,
лишним её делает только дубль.
"""


def configure_logging(
    *,
    level: str = "INFO",
    json_output: bool = False,
    stream: TextIO | None = None,
) -> None:
    """Настраивает structlog и стандартный logging на единый вывод.

    В разработке удобнее читаемый вывод, в контейнере — JSON для сбора логов.

    Поток вывода выбирается вызывающим, потому что у stdio-транспорта MCP
    stdout занят самим протоколом: строка лога там ломает поток JSON-RPC.
    """
    logging.basicConfig(
        format="%(message)s",
        stream=stream or sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    for name in SELF_HANDLED_LOGGERS:
        logging.getLogger(name).propagate = False

    renderer: Any = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if json_output
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
