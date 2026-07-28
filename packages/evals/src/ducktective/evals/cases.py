import json
from dataclasses import (
    dataclass,
    field,
)
from pathlib import (
    Path,
)
from typing import (
    Any,
)

from ducktective.core.review.entities import (
    Finding,
)
from ducktective.core.review.value_objects import (
    FindingCategory,
    Severity,
)


SEVERITY_RANK = {
    Severity.NITPICK: 1,
    Severity.MINOR: 2,
    Severity.MAJOR: 3,
    Severity.CRITICAL: 4,
}


@dataclass(frozen=True, kw_only=True)
class Expectation:
    """Что считается правильным ответом на случай.

    Совпадение проверяется по словам, а не по точной формулировке: модель
    вольна называть проблему своими словами, но обязана назвать её суть.
    Пустое ожидание означает чистый случай — там правильный ответ «молчание».
    """

    category: FindingCategory | None = None
    min_severity: Severity | None = None
    keywords: tuple[str, ...] = ()

    @property
    def is_clean(self) -> bool:
        return not self.keywords and self.category is None

    def matched_by(self, finding: Finding) -> bool:
        if self.is_clean:
            return False

        text = f"{finding.title} {finding.body_markdown}".lower()
        return any(keyword.lower() in text for keyword in self.keywords)

    def severity_is_adequate(self, finding: Finding) -> bool:
        if self.min_severity is None:
            return True
        return SEVERITY_RANK[finding.severity] >= SEVERITY_RANK[self.min_severity]

    def category_is_right(self, finding: Finding) -> bool:
        return self.category is None or finding.category is self.category


@dataclass(frozen=True, kw_only=True)
class EvalCase:
    name: str
    file_path: str
    patch: str
    expectation: Expectation
    tags: tuple[str, ...] = ()

    @property
    def is_clean(self) -> bool:
        return self.expectation.is_clean


@dataclass(frozen=True, kw_only=True)
class EvalDataset:
    name: str
    description: str = ""
    cases: tuple[EvalCase, ...] = field(default_factory=tuple)

    @property
    def defect_cases(self) -> tuple[EvalCase, ...]:
        return tuple(case for case in self.cases if not case.is_clean)

    @property
    def clean_cases(self) -> tuple[EvalCase, ...]:
        return tuple(case for case in self.cases if case.is_clean)


def load_dataset(path: Path) -> EvalDataset:
    """Читает набор случаев из файла.

    Набор лежит вне репозитория: в нём код, который туда попадать не должен.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    return EvalDataset(
        name=payload["name"],
        description=payload.get("description", ""),
        cases=tuple(_to_case(item) for item in payload["cases"]),
    )


def _to_case(payload: dict[str, Any]) -> EvalCase:
    expected: dict[str, Any] = payload.get("expected") or {}
    category = expected.get("category")
    severity = expected.get("min_severity")

    return EvalCase(
        name=str(payload["name"]),
        file_path=str(payload["file_path"]),
        patch=str(payload["patch"]),
        tags=tuple(str(tag) for tag in payload.get("tags") or ()),
        expectation=Expectation(
            category=FindingCategory(category) if category else None,
            min_severity=Severity(severity) if severity else None,
            keywords=tuple(str(keyword) for keyword in expected.get("keywords") or ()),
        ),
    )
