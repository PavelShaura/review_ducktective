from dataclasses import (
    dataclass,
    field,
)

from ducktective.core.review.entities import (
    Finding,
)
from ducktective.evals.cases import (
    EvalCase,
)


@dataclass(frozen=True, kw_only=True)
class CaseOutcome:
    """Что система ответила на один случай."""

    case: EvalCase
    findings: tuple[Finding, ...] = ()
    failure: str | None = None
    had_context: bool = False

    @property
    def matched(self) -> tuple[Finding, ...]:
        return tuple(
            finding for finding in self.findings if self.case.expectation.matched_by(finding)
        )

    @property
    def found_expected(self) -> bool:
        return bool(self.matched)


@dataclass(frozen=True, kw_only=True)
class Metrics:
    """Итог прогона набора.

    Precision в строгом смысле — доля находок, признанных полезными, — здесь
    не считается: для неё нужна человеческая разметка, а набор со внесёнными
    дефектами знает только про свои дефекты. Его сильная сторона в другом:
    воспроизводимость и независимость от того, сколько успели разметить.
    """

    cases: int = 0
    defects: int = 0
    found: int = 0
    clean_cases: int = 0
    clean_with_findings: int = 0
    findings_on_clean: int = 0
    severity_adequate: int = 0
    category_right: int = 0
    failures: int = 0
    findings_total: int = 0
    cases_with_context: int = 0

    @property
    def recall(self) -> float:
        """Доля внесённых дефектов, которые система назвала."""
        return self.found / self.defects if self.defects else 0.0

    @property
    def false_alarm_rate(self) -> float:
        """Доля чистых случаев, на которых система что-то нашла.

        Прямая замена FP rate, не требующая разметки: на этих диффах
        придраться не к чему по построению.
        """
        return self.clean_with_findings / self.clean_cases if self.clean_cases else 0.0

    @property
    def severity_accuracy(self) -> float:
        return self.severity_adequate / self.found if self.found else 0.0

    @property
    def category_accuracy(self) -> float:
        return self.category_right / self.found if self.found else 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "recall": round(self.recall, 4),
            "false_alarm_rate": round(self.false_alarm_rate, 4),
            "severity_accuracy": round(self.severity_accuracy, 4),
            "category_accuracy": round(self.category_accuracy, 4),
            "cases": self.cases,
            "defects": self.defects,
            "found": self.found,
            "clean_cases": self.clean_cases,
            "clean_with_findings": self.clean_with_findings,
            "findings_total": self.findings_total,
            "failures": self.failures,
            "cases_with_context": self.cases_with_context,
        }


@dataclass
class MetricsBuilder:
    outcomes: list[CaseOutcome] = field(default_factory=list)

    def add(self, outcome: CaseOutcome) -> None:
        self.outcomes.append(outcome)

    def build(self) -> Metrics:
        defects = [outcome for outcome in self.outcomes if not outcome.case.is_clean]
        clean = [outcome for outcome in self.outcomes if outcome.case.is_clean]
        found = [outcome for outcome in defects if outcome.found_expected]

        return Metrics(
            cases=len(self.outcomes),
            defects=len(defects),
            found=len(found),
            clean_cases=len(clean),
            clean_with_findings=sum(1 for outcome in clean if outcome.findings),
            findings_on_clean=sum(len(outcome.findings) for outcome in clean),
            severity_adequate=sum(
                1
                for outcome in found
                if any(
                    outcome.case.expectation.severity_is_adequate(finding)
                    for finding in outcome.matched
                )
            ),
            category_right=sum(
                1
                for outcome in found
                if any(
                    outcome.case.expectation.category_is_right(finding)
                    for finding in outcome.matched
                )
            ),
            failures=sum(1 for outcome in self.outcomes if outcome.failure),
            cases_with_context=sum(1 for outcome in self.outcomes if outcome.had_context),
            findings_total=sum(len(outcome.findings) for outcome in self.outcomes),
        )
