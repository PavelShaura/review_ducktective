from datetime import (
    UTC,
    datetime,
)
from uuid import (
    uuid4,
)

from ducktective.api.cli import (
    _exit_code,
)
from ducktective.core.diff.value_objects import (
    DiffSide,
)
from ducktective.core.review.entities import (
    Finding,
    ReviewRun,
)
from ducktective.core.review.value_objects import (
    FindingCategory,
    FindingProducer,
    FindingStatus,
    ReviewSource,
    ReviewStatus,
    Severity,
)
from ducktective.core.types import (
    CommitSha,
    FindingId,
    RepositoryId,
    ReviewRunId,
    TenantId,
)


def build_run(*severities: Severity, rejected: bool = False) -> ReviewRun:
    run = ReviewRun(
        id=ReviewRunId(uuid4()),
        tenant_id=TenantId(uuid4()),
        repository_id=RepositoryId(uuid4()),
        source=ReviewSource.LOCAL_DIFF,
        base_sha=CommitSha("a" * 40),
        head_sha=CommitSha("b" * 40),
        status=ReviewStatus.COMPLETED,
        created_at=datetime.now(UTC),
    )
    for index, severity in enumerate(severities):
        run.findings.append(
            Finding(
                id=FindingId(uuid4()),
                file_path="app/service.py",
                line_start=10 + index,
                line_end=10 + index,
                side=DiffSide.NEW,
                severity=severity,
                category=FindingCategory.CORRECTNESS,
                title=f"Находка {index}",
                body_markdown="Описание",
                dedup_key=f"key-{index}",
                producer=FindingProducer.LLM,
                producer_name="reviewer:single-pass",
                status=FindingStatus.REJECTED if rejected else FindingStatus.VERIFIED,
            )
        )
    return run


def test_without_threshold_always_zero() -> None:
    run = build_run(Severity.CRITICAL)

    assert _exit_code(run, None) == 0


def test_finding_above_threshold_fails() -> None:
    run = build_run(Severity.CRITICAL)

    assert _exit_code(run, "major") == 1


def test_finding_at_threshold_fails() -> None:
    run = build_run(Severity.MAJOR)

    assert _exit_code(run, "major") == 1


def test_finding_below_threshold_passes() -> None:
    run = build_run(Severity.MINOR, Severity.NITPICK)

    assert _exit_code(run, "major") == 0


def test_rejected_findings_are_ignored() -> None:
    run = build_run(Severity.CRITICAL, rejected=True)

    assert _exit_code(run, "critical") == 0


def test_empty_run_passes() -> None:
    run = build_run()

    assert _exit_code(run, "nitpick") == 0
