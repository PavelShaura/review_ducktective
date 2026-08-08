from dataclasses import (
    dataclass,
)
from typing import (
    Protocol,
)

from ducktective.core.llm.value_objects import (
    LlmUsage,
    ModelRequirements,
)
from ducktective.core.retrieval.context import (
    DiffContext,
)
from ducktective.core.retrieval.navigation import (
    CodeFragment,
    CodeNavigator,
)
from ducktective.core.review.drafts import (
    FindingDraft,
)
from ducktective.core.review.entities import (
    ReviewFile,
    ReviewRun,
)
from ducktective.core.review.investigation import (
    InvestigationSink,
)
from ducktective.core.review.pipeline import (
    PipelineOutcome,
    PipelineRequest,
)
from ducktective.core.types import (
    RepositoryId,
    ReviewRunId,
)


class ReviewRunRepository(Protocol):
    """Доступ к агрегату ReviewRun. Транзакцию не фиксирует."""

    def add(self, run: ReviewRun) -> None: ...

    async def get(self, run_id: ReviewRunId) -> ReviewRun: ...

    async def list_for_repository(
        self,
        repository_id: RepositoryId,
        *,
        limit: int = 50,
    ) -> list[ReviewRun]: ...

    async def remove(self, run: ReviewRun) -> None: ...


@dataclass(frozen=True, kw_only=True)
class FileReviewResult:
    drafts: list[FindingDraft]
    usage: LlmUsage
    model: str
    is_cache_hit: bool = False
    shown: tuple[CodeFragment, ...] = ()
    """Код, который ревьюер посмотрел инструментами.

    Едет обратно ради проверки доказательств: цитата из ответа инструмента —
    такое же показанное окружение, как собранный заранее контекст, и без
    этого поля агентная находка отбраковывается именно за то, ради чего
    агент и заводился (D-008).
    """


class CancellationCheck(Protocol):
    """Спрашивает, не попросили ли прекратить расследование.

    Конвейер отвечает за то, когда спросить, а use case — за то, где хранится
    ответ. Прервать сам запрос к модели нечем, поэтому проверка имеет смысл
    только между файлами.
    """

    async def __call__(self) -> bool: ...


@dataclass(frozen=True, kw_only=True)
class ReviewSupport:
    """То, что ревьюер получает от прогона на время чтения одного файла.

    Собрано в один объект, потому что все три вещи приходят из одного места
    и живут ровно столько, сколько прогон: инструменты его репозитория и
    ревизии, лента его расследования и его же просьба прекратить. Ревьюер
    при этом собирается один раз на приложение и ни о чём из этого заранее
    не знает.
    """

    navigator: CodeNavigator | None = None
    sink: InvestigationSink | None = None
    cancellation: CancellationCheck | None = None

    async def stop_requested(self) -> bool:
        """Просили ли прекратить.

        Спрашивается изнутри чтения файла, а не только между файлами: агентный
        цикл обращается к модели до шести раз, и на локальной модели это
        десяток минут, в течение которых нажатое «прекратить» ничего не делало.
        """
        if self.cancellation is None:
            return False
        return await self.cancellation()


class CodeReviewer(Protocol):
    """Ревьюер одного файла. Реализация решает, чем именно он думает."""

    name: str

    async def review_file(
        self,
        file: ReviewFile,
        *,
        patch_text: str,
        requirements: ModelRequirements,
        context: DiffContext | None = None,
        support: ReviewSupport | None = None,
    ) -> FileReviewResult:
        """Читает файл и возвращает черновики находок.

        Поддержка прогона приходит вызовом, а не конструктором: она привязана
        к прогону, а ревьюер собран на приложение. Реализация, которой она
        не нужна, её игнорирует.
        """
        ...


class ReviewNavigators(Protocol):
    """Чем прогон ходит по коду.

    Ответ зависит от того, собран ли индекс: граф и векторы там, где собран,
    поиск по ревизии там, где нет (D-021). `None` означает, что инструментов
    нет вовсе — ни индекса, ни рабочего каталога, — и агентный режим тогда
    не начинается.
    """

    def for_request(self, request: PipelineRequest) -> CodeNavigator | None: ...


class ReviewPipeline(Protocol):
    """Путь от подготовленных файлов до проверенных находок.

    Объявлен портом, потому что use case зависит от того, что дифф можно
    прогнать через конвейер, но не от того, что конвейер — граф LangGraph.
    """

    async def run(
        self,
        request: PipelineRequest,
        *,
        cancellation: CancellationCheck | None = None,
        resume: bool = False,
    ) -> PipelineOutcome:
        """Прогоняет дифф; при `resume` продолжает прерванный ход.

        Продолжение опирается на сохранённый ход прогона: уже прочитанные
        пары «файл × ревьюер» не читаются заново. Если сохранять ход нечем,
        продолжение равносильно прогону с начала — и это честнее отказа,
        потому что результат тот же, просто дороже.
        """
        ...

    async def forget(self, run_id: ReviewRunId) -> None:
        """Забывает сохранённый ход прогона.

        Зовётся и перед прогоном с начала, и после успешного завершения:
        продолжать законченное нечего, а в состоянии лежат патчи всех файлов
        и весь собранный контекст.
        """
        ...
