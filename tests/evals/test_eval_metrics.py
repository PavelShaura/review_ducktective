from uuid import (
    uuid4,
)

from ducktective.core.diff.value_objects import (
    DiffSide,
)
from ducktective.core.review.entities import (
    Finding,
)
from ducktective.core.review.value_objects import (
    FindingCategory,
    FindingProducer,
    Severity,
)
from ducktective.core.types import (
    FindingId,
)
from ducktective.evals.cases import (
    EvalCase,
    Expectation,
)
from ducktective.evals.metrics import (
    CaseOutcome,
    Metrics,
    MetricsBuilder,
)


def finding(
    title: str = "Строка собирается конкатенацией",
    body: str = "Значение подставляется в SQL напрямую — это инъекция",
    severity: Severity = Severity.CRITICAL,
    category: FindingCategory = FindingCategory.SECURITY,
) -> Finding:
    return Finding(
        id=FindingId(uuid4()),
        file_path="app/repository.py",
        line_start=12,
        line_end=12,
        side=DiffSide.NEW,
        severity=severity,
        category=category,
        title=title,
        body_markdown=body,
        dedup_key="key",
        producer=FindingProducer.LLM,
        producer_name="reviewer:single-pass",
    )


def defect_case(
    *,
    keywords: tuple[str, ...] = ("инъекц",),
    category: FindingCategory | None = FindingCategory.SECURITY,
    min_severity: Severity | None = Severity.CRITICAL,
) -> EvalCase:
    return EvalCase(
        name="sql-injection",
        file_path="app/repository.py",
        patch="@@",
        expectation=Expectation(
            category=category,
            min_severity=min_severity,
            keywords=keywords,
        ),
    )


def clean_case() -> EvalCase:
    return EvalCase(
        name="clean",
        file_path="app/format.py",
        patch="@@",
        expectation=Expectation(),
    )


def metrics_of(*outcomes: CaseOutcome) -> Metrics:
    builder = MetricsBuilder()
    for outcome in outcomes:
        builder.add(outcome)
    return builder.build()


def test_defect_named_in_other_words_still_counts() -> None:
    """Модель вправе формулировать по-своему, но обязана назвать суть."""
    metrics = metrics_of(CaseOutcome(case=defect_case(), findings=(finding(),)))

    assert metrics.recall == 1.0


def test_finding_about_something_else_does_not_count() -> None:
    outcome = CaseOutcome(
        case=defect_case(),
        findings=(finding(title="Длинная строка", body="Нарушение форматирования"),),
    )

    assert metrics_of(outcome).recall == 0.0


def test_silence_on_defect_is_a_miss() -> None:
    assert metrics_of(CaseOutcome(case=defect_case())).recall == 0.0


def test_finding_on_clean_case_is_a_false_alarm() -> None:
    metrics = metrics_of(CaseOutcome(case=clean_case(), findings=(finding(),)))

    assert metrics.false_alarm_rate == 1.0


def test_silence_on_clean_case_is_correct() -> None:
    metrics = metrics_of(CaseOutcome(case=clean_case()))

    assert metrics.false_alarm_rate == 0.0
    assert metrics.recall == 0.0


def test_understated_severity_is_counted_separately() -> None:
    """Находка засчитана, но уровень занижен — это разные вещи."""
    outcome = CaseOutcome(
        case=defect_case(),
        findings=(finding(severity=Severity.NITPICK),),
    )

    metrics = metrics_of(outcome)
    assert metrics.recall == 1.0
    assert metrics.severity_accuracy == 0.0


def test_wrong_category_is_counted_separately() -> None:
    outcome = CaseOutcome(
        case=defect_case(),
        findings=(finding(category=FindingCategory.STYLE),),
    )

    metrics = metrics_of(outcome)
    assert metrics.recall == 1.0
    assert metrics.category_accuracy == 0.0


def test_failed_case_is_visible_in_metrics() -> None:
    metrics = metrics_of(CaseOutcome(case=defect_case(), failure="модель недоступна"))

    assert metrics.failures == 1
    assert metrics.recall == 0.0


def test_context_usage_is_reported() -> None:
    """Прогон «с контекстом», где контекст не собрался, обязан выдать себя."""
    metrics = metrics_of(
        CaseOutcome(case=defect_case(), findings=(finding(),), had_context=False),
        CaseOutcome(case=clean_case(), had_context=False),
    )

    assert metrics.cases_with_context == 0


def test_clean_case_expectation_matches_nothing() -> None:
    assert Expectation().matched_by(finding()) is False
