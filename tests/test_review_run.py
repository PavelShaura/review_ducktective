from uuid import (
    uuid4,
)

import pytest

from ducktective.core.diff.entities import (
    Diff,
)
from ducktective.core.diff.value_objects import (
    DiffSide,
)
from ducktective.core.exceptions import (
    InvariantViolationError,
)
from ducktective.core.review.dedup import (
    build_dedup_key,
)
from ducktective.core.review.entities import (
    Evidence,
    Finding,
    ReviewRun,
)
from ducktective.core.review.events import (
    FindingRecorded,
    ReviewRunCreated,
)
from ducktective.core.review.value_objects import (
    EvidenceKind,
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
    TenantId,
)
from ducktective.vcs.diff_parser import (
    UnifiedDiffParser,
)
from tests.diff_fixtures import (
    MODIFIED_AND_ADDED_PATCH,
)


def build_diff() -> Diff:
    return UnifiedDiffParser().parse(
        MODIFIED_AND_ADDED_PATCH,
        base_sha=CommitSha("a" * 40),
        head_sha=CommitSha("b" * 40),
    )


def build_run() -> ReviewRun:
    return ReviewRun.create(
        tenant_id=TenantId(uuid4()),
        repository_id=RepositoryId(uuid4()),
        source=ReviewSource.LOCAL_DIFF,
        diff=build_diff(),
    )


def build_finding(*, title: str = "N+1 query", code: str = "for item in items:") -> Finding:
    return Finding(
        id=FindingId(uuid4()),
        file_path="app/service.py",
        line_start=11,
        line_end=12,
        side=DiffSide.NEW,
        severity=Severity.MAJOR,
        category=FindingCategory.PERFORMANCE,
        title=title,
        body_markdown="Запрос выполняется в цикле",
        dedup_key=build_dedup_key(
            category=FindingCategory.PERFORMANCE,
            rule_id=None,
            symbol_name="ReportBuilder.build",
            file_path="app/service.py",
            code_fragment=code,
        ),
        producer=FindingProducer.LLM,
        producer_name="reviewer:performance",
    )


def test_creation_records_event_and_files() -> None:
    run = build_run()
    events = run.pull_events()

    assert run.status is ReviewStatus.QUEUED
    assert len(run.files) == 2
    assert isinstance(events[0], ReviewRunCreated)


def test_empty_diff_is_rejected() -> None:
    empty_diff = Diff(base_sha=CommitSha("a" * 40), head_sha=CommitSha("b" * 40), files=[])

    with pytest.raises(InvariantViolationError):
        ReviewRun.create(
            tenant_id=TenantId(uuid4()),
            repository_id=RepositoryId(uuid4()),
            source=ReviewSource.LOCAL_DIFF,
            diff=empty_diff,
        )


def test_finding_is_added_with_event() -> None:
    run = build_run()
    run.pull_events()

    added = run.add_finding(build_finding())
    events = run.pull_events()

    assert added is True
    assert isinstance(events[0], FindingRecorded)
    assert run.severity_totals == {"major": 1}


def test_duplicate_finding_is_ignored() -> None:
    run = build_run()

    run.add_finding(build_finding())
    added_again = run.add_finding(build_finding(title="Другой заголовок"))

    assert added_again is False
    assert len(run.findings) == 1


def test_dedup_key_ignores_whitespace_and_line_numbers() -> None:
    first = build_dedup_key(
        category=FindingCategory.CORRECTNESS,
        rule_id=None,
        symbol_name="Builder.build",
        file_path="app/service.py",
        code_fragment="if   value  is None:",
    )
    second = build_dedup_key(
        category=FindingCategory.CORRECTNESS,
        rule_id=None,
        symbol_name="Builder.build",
        file_path="app/service.py",
        code_fragment="if value is None:",
    )

    assert first == second


def test_status_transitions_emit_events() -> None:
    run = build_run()
    run.pull_events()

    run.mark_running()
    run.mark_completed()

    assert run.status is ReviewStatus.COMPLETED
    assert run.started_at is not None
    assert run.finished_at is not None
    assert len(run.pull_events()) == 2


def test_finished_run_rejects_new_findings() -> None:
    run = build_run()
    run.mark_running()
    run.mark_completed()

    with pytest.raises(InvariantViolationError):
        run.add_finding(build_finding())


def test_finding_without_evidence_cannot_be_verified() -> None:
    finding = build_finding()

    with pytest.raises(InvariantViolationError):
        finding.verify()


def test_finding_with_evidence_is_verified() -> None:
    finding = build_finding()
    finding.evidence.append(
        Evidence(
            kind=EvidenceKind.QUOTED_CODE,
            file_path="app/service.py",
            snippet="for item in items:",
            line_start=11,
            line_end=11,
        )
    )

    finding.verify()

    assert finding.status is FindingStatus.VERIFIED


def test_rejected_findings_are_excluded_from_totals() -> None:
    run = build_run()
    finding = build_finding()
    run.add_finding(finding)

    finding.reject()

    assert run.severity_totals == {}
