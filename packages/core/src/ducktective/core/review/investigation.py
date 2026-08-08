from dataclasses import (
    dataclass,
)
from enum import (
    StrEnum,
)
from typing import (
    Protocol,
)

from ducktective.core.types import (
    ReviewRunId,
)


MAX_STEP_DETAIL_CHARS = 2000
"""Сколько от шага сохраняется для человека.

Показывается ход расследования, а не содержимое кодовой базы: результат
инструмента бывает в десятки тысяч символов, и держать его целиком ради
ленты незачем. Модель при этом видит свой полный результат — обрезается
то, что уходит в трассу.
"""


class StepKind(StrEnum):
    """Что именно произошло на шаге.

    Разделено по тому, как это читается человеком: намерение, обращение
    к инструменту, ответ инструмента, итог. Без разделения лента
    превращается в поток текста, где не видно, чем агент занят прямо сейчас.
    """

    THOUGHT = "thought"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ANSWER = "answer"
    FALLBACK = "fallback"


@dataclass(frozen=True, kw_only=True)
class InvestigationStep:
    """Один шаг расследования по одному файлу.

    Прогон здесь не назван: ревьюер его не знает и знать не должен — он читает
    файл, а не ведёт дело. Прогон известен тому, кто слушает, и подставляется
    при записи.
    """

    file_path: str
    number: int
    kind: StepKind
    tool_name: str | None = None
    arguments: str | None = None
    detail: str = ""
    duration_ms: int = 0
    is_error: bool = False


@dataclass(frozen=True, kw_only=True)
class RecordedStep:
    """Записанный шаг вместе с местом в ленте.

    Номер шага у ревьюера свой на каждый файл, а лента прогона общая, поэтому
    порядок в ней задаёт `cursor`: по нему же лента и дочитывается.
    """

    cursor: int
    step: InvestigationStep


class InvestigationLog(Protocol):
    """Хранилище хода расследования.

    Записи не входят в агрегат прогона: они появляются по ходу работы
    конвейера, короткими транзакциями, пока сам прогон открыт минутами.
    """

    async def append(self, run_id: ReviewRunId, step: InvestigationStep) -> RecordedStep: ...

    async def list_for_run(
        self,
        run_id: ReviewRunId,
        *,
        after: int = 0,
        limit: int = 500,
    ) -> list[RecordedStep]:
        """Шаги прогона по порядку, начиная со следующего за `after`."""
        ...


class InvestigationSink(Protocol):
    """Куда уходит ход расследования.

    Объявлен портом, потому что цикл обязан рассказывать о себе всегда,
    а слушателей у него разное число: в автономном CLI никого, в прогоне
    через воркер — хранилище и лента в интерфейсе. Молчащий агент отличается
    от одноразового прохода только счётом времени.
    """

    async def record(self, step: InvestigationStep) -> None: ...


class InvestigationSinks(Protocol):
    """Слушатель хода — по одному на прогон.

    Прогон известен здесь, а не ревьюеру: ревьюер читает файл, а не ведёт дело,
    и подставлять идентификатор прогона в каждый его шаг — работа того, кто
    этот прогон затеял.
    """

    def for_run(self, run_id: ReviewRunId) -> InvestigationSink: ...


class NullInvestigationSink:
    """Слушатель, которого нет.

    Ставится там, где ход расследования никому не нужен: в тестах и
    в автономном прогоне без хранилища.
    """

    async def record(self, step: InvestigationStep) -> None:
        return None
