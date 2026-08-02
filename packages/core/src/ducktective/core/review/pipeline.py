from dataclasses import (
    dataclass,
    field,
)

from ducktective.core.llm.value_objects import (
    LlmUsage,
    ModelRequirements,
)
from ducktective.core.review.entities import (
    Finding,
    ReviewFile,
)
from ducktective.core.types import (
    RepositoryId,
)


@dataclass(frozen=True, kw_only=True)
class PipelineRequest:
    """Всё, что конвейеру нужно для прогона.

    Ни базы, ни агрегата: use case читает прогон, отдаёт сюда файлы и забирает
    находки обратно. Иначе граф пришлось бы пускать внутрь транзакции, а он
    работает минутами.
    """

    repository_id: RepositoryId
    files: tuple[ReviewFile, ...]
    requirements: ModelRequirements


@dataclass(frozen=True, kw_only=True)
class PipelineOutcome:
    """Проверенные находки вместе с тем, что было отброшено по дороге.

    Отброшенное разложено по причинам: «находок 0» иначе означает и что модель
    ничего не нашла, и что все её ответы не прошли проверку, а чинить эти два
    случая нужно по-разному.
    """

    findings: tuple[Finding, ...] = ()
    usage: LlmUsage = field(default_factory=LlmUsage)
    proposed: int = 0
    discarded_outside_diff: int = 0
    discarded_without_evidence: int = 0
    discarded_as_duplicate: int = 0
    failed_files: tuple[str, ...] = ()
    unreviewed_files: tuple[str, ...] = ()
    """Файлы, которых не прочитал ни один ревьюер.

    Считается отдельно от `failed_files`: сбой случается на паре «файл ×
    ревьюер», и файл, упавший у одного из четверых, всё же проревьюен. Меряя
    беду в парах, прогон отчитывается о непроверенных файлах, которых нет.
    """

    files_with_context: int = 0
    reviewed_files: int = 0
    is_cancelled: bool = False
