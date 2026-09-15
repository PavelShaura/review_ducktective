import operator
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Annotated,
)

from pydantic import (
    BaseModel,
    Field,
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
from ducktective.core.review.degradation import (
    NodeDegradation,
)
from ducktective.core.review.drafts import (
    FindingDraft,
)
from ducktective.core.review.entities import (
    Finding,
    ReviewFile,
    RunDiff,
)
from ducktective.core.review.investigation import (
    InvestigationSink,
)
from ducktective.core.review.pipeline import (
    PipelineRequest,
)
from ducktective.core.review.ports import (
    CancellationCheck,
    FindingHistory,
)
from ducktective.core.review.value_objects import (
    ReviewLanguage,
)
from ducktective.core.types import (
    RepositoryId,
)


@dataclass(frozen=True, kw_only=True)
class ReviewRuntimeContext:
    """То, что меняется от прогона к прогону, но не является состоянием.

    Проверка на отмену — вызов в базу, и в состоянии графа ей не место:
    состояние обязано остаться сериализуемым, иначе checkpointer из шага 4.3
    не сможет его сохранить. Навигатор здесь по той же причине: он держит
    сессию базы или путь к репозиторию, и сохранять его в чекпоинт нечем.
    """

    cancellation: CancellationCheck | None = None
    navigator: CodeNavigator | None = None
    sink: InvestigationSink | None = None
    diff: RunDiff = field(default_factory=RunDiff)
    history: FindingHistory | None = None
    repository_id: RepositoryId | None = None
    language: ReviewLanguage = ReviewLanguage.RU


class FileReviewTask(BaseModel):
    """Вход узла-ревьюера: один файл, отданный одному ревьюеру.

    Единица распараллеливания — пара «файл × ревьюер», а не файл: четыре
    ревьюера из фазы 4.2 смотрят один и тот же дифф разными глазами.

    Доменные типы объявлены как есть, а не спрятаны за `InstanceOf`: иначе
    pydantic не знает их схемы и при восстановлении из чекпоинта отдаёт
    словари вместо объектов — прогон падает ровно в момент продолжения.
    """

    file: ReviewFile
    context: DiffContext | None = None
    reviewer_name: str
    requirements: ModelRequirements


class FileDrafts(BaseModel):
    """Что вернул один ревьюер по одному файлу."""

    file: ReviewFile
    context: DiffContext | None = None
    reviewer_name: str
    drafts: tuple[FindingDraft, ...] = ()
    shown: tuple[CodeFragment, ...] = ()
    usage: LlmUsage = Field(default_factory=LlmUsage)
    degradation: NodeDegradation | None = None


class MergedDraft(BaseModel):
    """Черновик, переживший слияние, вместе с тем, что нужно для проверки."""

    draft: FindingDraft
    file: ReviewFile
    context: DiffContext | None = None
    shown: tuple[CodeFragment, ...] = ()
    reviewer_name: str


class ReviewGraphState(BaseModel):
    """Состояние прогона по узлам.

    Счётчики отброшенного лежат здесь, а не считаются в конце: причина отбраковки
    известна только тому узлу, который её отбраковал.
    """

    request: PipelineRequest

    contexts: dict[str, DiffContext] = Field(default_factory=dict)
    files_with_context: int = 0
    degradations: Annotated[list[NodeDegradation], operator.add] = Field(default_factory=list)
    """Отметки узлов, не ветвящихся по файлам.

    Ревьюеры кладут свои в `results`: там отметка едет вместе с файлом,
    по которому считаются непрочитанные.
    """

    tasks: tuple[FileReviewTask, ...] = ()
    results: Annotated[list[FileDrafts], operator.add] = Field(default_factory=list)

    merged: tuple[MergedDraft, ...] = ()
    displaced: tuple[MergedDraft, ...] = ()
    proposed: int = 0

    findings: tuple[Finding, ...] = ()
    discarded_outside_diff: int = 0
    discarded_without_evidence: int = 0
    discarded_unproven_claim: int = 0
    discarded_as_duplicate: int = 0
