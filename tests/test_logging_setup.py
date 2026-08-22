import logging

from ducktective.observability.logging import (
    SELF_HANDLED_LOGGERS,
    configure_logging,
)


class CapturingHandler(logging.Handler):
    """Всё, что дошло до корневого логгера."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record.getMessage())


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
