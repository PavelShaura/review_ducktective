import operator
from dataclasses import (
    dataclass,
)
from typing import (
    Annotated,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    InstanceOf,
)

from ducktective.core.llm.value_objects import (
    LlmUsage,
    ModelRequirements,
)
from ducktective.core.retrieval.context import (
    DiffContext,
)
from ducktective.core.review.drafts import (
    FindingDraft,
)
from ducktective.core.review.entities import (
    Finding,
    ReviewFile,
)
from ducktective.core.review.pipeline import (
    PipelineRequest,
)
from ducktective.core.review.ports import (
    CancellationCheck,
)


_MODEL_CONFIG = ConfigDict(arbitrary_types_allowed=True)


@dataclass(frozen=True, kw_only=True)
class ReviewRuntimeContext:
    """То, что меняется от прогона к прогону, но не является состоянием.

    Проверка на отмену — вызов в базу, и в состоянии графа ей не место:
    состояние обязано остаться сериализуемым, иначе checkpointer из шага 4.3
    не сможет его сохранить.
    """

    cancellation: CancellationCheck | None = None


class FileReviewTask(BaseModel):
    """Вход узла-ревьюера: один файл, отданный одному ревьюеру.

    Единица распараллеливания — пара «файл × ревьюер», а не файл: четыре
    ревьюера из фазы 4.2 смотрят один и тот же дифф разными глазами.
    """

    model_config = _MODEL_CONFIG

    file: InstanceOf[ReviewFile]
    context: InstanceOf[DiffContext] | None = None
    reviewer_name: str
    requirements: InstanceOf[ModelRequirements]


class FileDrafts(BaseModel):
    """Что вернул один ревьюер по одному файлу."""

    model_config = _MODEL_CONFIG

    file: InstanceOf[ReviewFile]
    context: InstanceOf[DiffContext] | None = None
    reviewer_name: str
    drafts: tuple[InstanceOf[FindingDraft], ...] = ()
    usage: InstanceOf[LlmUsage] = Field(default_factory=LlmUsage)
    failure: str | None = None
    is_cancelled: bool = False


class MergedDraft(BaseModel):
    """Черновик, переживший слияние, вместе с тем, что нужно для проверки."""

    model_config = _MODEL_CONFIG

    draft: InstanceOf[FindingDraft]
    file: InstanceOf[ReviewFile]
    context: InstanceOf[DiffContext] | None = None
    reviewer_name: str


class ReviewGraphState(BaseModel):
    """Состояние прогона по узлам.

    Счётчики отброшенного лежат здесь, а не считаются в конце: причина отбраковки
    известна только тому узлу, который её отбраковал.
    """

    model_config = _MODEL_CONFIG

    request: InstanceOf[PipelineRequest]

    contexts: dict[str, InstanceOf[DiffContext]] = Field(default_factory=dict)
    files_with_context: int = 0

    tasks: tuple[FileReviewTask, ...] = ()
    results: Annotated[list[FileDrafts], operator.add] = Field(default_factory=list)

    merged: tuple[MergedDraft, ...] = ()
    displaced: tuple[MergedDraft, ...] = ()
    proposed: int = 0

    findings: tuple[InstanceOf[Finding], ...] = ()
    discarded_outside_diff: int = 0
    discarded_without_evidence: int = 0
    discarded_as_duplicate: int = 0
