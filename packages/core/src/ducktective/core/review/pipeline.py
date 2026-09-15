from dataclasses import (
    dataclass,
    field,
)
from pathlib import (
    Path,
)

from ducktective.core.llm.value_objects import (
    LlmUsage,
    ModelRequirements,
)
from ducktective.core.review.degradation import (
    NodeDegradation,
)
from ducktective.core.review.entities import (
    Finding,
    ReviewFile,
)
from ducktective.core.review.value_objects import (
    ReviewLanguage,
)
from ducktective.core.types import (
    CommitSha,
    RepositoryId,
    ReviewRunId,
)


@dataclass(frozen=True, kw_only=True)
class PipelineRequest:
    """Всё, что конвейеру нужно для прогона.

    Ни базы, ни агрегата: use case читает прогон, отдаёт сюда файлы и забирает
    находки обратно. Иначе граф пришлось бы пускать внутрь транзакции, а он
    работает минутами.
    """

    run_id: ReviewRunId
    """Кем прогон назовётся в сохранённом ходе.

    Агрегата конвейер не получает, но узнать прерванный прогон в лицо ему
    нужно: без имени продолжать нечего.
    """

    repository_id: RepositoryId
    files: tuple[ReviewFile, ...]
    requirements: ModelRequirements
    language: ReviewLanguage = ReviewLanguage.RU
    """На каком языке писать находки. Русский — для прогонов, заведённых раньше."""

    head_sha: CommitSha | None = None
    """Ревизия, которую читают инструменты навигации.

    Без неё режим без индекса невозможен: git отвечает про названную ревизию,
    а не про рабочую копию (D-021).
    """

    repository_path: Path | None = None
    """Где лежит репозиторий. Нужен тому же режиму без индекса."""

    index_revision: CommitSha | None = None
    """Ревизия, на которой собран индекс, если он собран.

    Читает use case, а не конвейер: состояние индекса лежит в базе, а конвейер
    к ней не ходит. Ревизия важнее самого факта сборки — индекс, собранный
    на другом коммите, отвечает про другой код: изменённых символов в нём нет,
    и `find_callers` возвращает пустоту, которую модель принимает за
    «вызывающих не существует». На живом прогоне 2026-08-08 это дало две
    ложные находки из четырёх.
    """

    @property
    def index_matches_revision(self) -> bool:
        """Отвечает ли индекс про ту же ревизию, которую ревьюим."""
        return self.index_revision is not None and self.index_revision == self.head_sha


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
    discarded_unproven_claim: int = 0
    """Находки, утверждавшие о чужом коде, не посмотрев его.

    Считается отдельно от «без доказательств»: там модель сослалась
    на несуществующую строку, здесь — сказала о вызывающих, ни одного
    из них не увидев. Первое лечится промптом, второе — тем, чтобы агент
    пользовался инструментами.
    """

    discarded_as_duplicate: int = 0
    degradations: tuple[NodeDegradation, ...] = ()
    """Кто именно не отработал и на каком файле.

    `failed_files` пересказывает то же самое строками для человека,
    а разбирательство начинается с вопроса, какой узел упал.
    """

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
