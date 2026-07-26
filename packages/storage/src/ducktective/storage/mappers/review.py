from uuid import (
    uuid4,
)

from ducktective.core.review.entities import (
    Evidence,
    Finding,
    FindingFeedback,
    ReviewFile,
    ReviewHunk,
    ReviewRun,
)
from ducktective.core.types import (
    CommitSha,
    FindingFeedbackId,
    FindingId,
    RepositoryId,
    ReviewFileId,
    ReviewHunkId,
    ReviewRunId,
    TenantId,
    UserId,
)
from ducktective.storage.models.review import (
    FindingEvidenceModel,
    FindingFeedbackModel,
    FindingModel,
    ReviewFileModel,
    ReviewHunkModel,
    ReviewRunModel,
)


def to_domain(model: ReviewRunModel) -> ReviewRun:
    return ReviewRun(
        id=ReviewRunId(model.id),
        tenant_id=TenantId(model.tenant_id),
        repository_id=RepositoryId(model.repository_id),
        source=model.source,
        base_sha=CommitSha(model.base_sha),
        head_sha=CommitSha(model.head_sha),
        status=model.status,
        created_at=model.created_at,
        created_by=UserId(model.created_by) if model.created_by is not None else None,
        external_pull_request_id=model.external_pull_request_id,
        started_at=model.started_at,
        finished_at=model.finished_at,
        failure_reason=model.failure_reason,
        tokens_input=model.tokens_input,
        tokens_output=model.tokens_output,
        cost_usd=model.cost_usd,
        files=[_file_to_domain(file_model) for file_model in model.files],
        findings=[_finding_to_domain(finding_model) for finding_model in model.findings],
    )


def to_model(run: ReviewRun) -> ReviewRunModel:
    return ReviewRunModel(
        id=run.id,
        tenant_id=run.tenant_id,
        repository_id=run.repository_id,
        source=run.source,
        external_pull_request_id=run.external_pull_request_id,
        base_sha=run.base_sha,
        head_sha=run.head_sha,
        status=run.status,
        totals=run.severity_totals,
        failure_reason=run.failure_reason,
        created_by=run.created_by,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        tokens_input=run.tokens_input,
        tokens_output=run.tokens_output,
        cost_usd=run.cost_usd,
        files=[_file_to_model(file) for file in run.files],
        findings=[_finding_to_model(finding) for finding in run.findings],
    )


def apply_changes(model: ReviewRunModel, run: ReviewRun) -> None:
    """Переносит изменения агрегата в ORM-модель.

    Файлы и блоки изменений неизменяемы после создания прогона, поэтому
    синхронизируются только статус, тайминги и находки.
    """
    model.status = run.status
    model.totals = run.severity_totals
    model.failure_reason = run.failure_reason
    model.started_at = run.started_at
    model.finished_at = run.finished_at
    model.tokens_input = run.tokens_input
    model.tokens_output = run.tokens_output
    model.cost_usd = run.cost_usd

    findings_by_id = {finding.id: finding for finding in run.findings}
    persisted_ids = {finding_model.id for finding_model in model.findings}

    for finding_id, finding in findings_by_id.items():
        if finding_id not in persisted_ids:
            model.findings.append(_finding_to_model(finding))

    for finding_model in model.findings:
        matching_finding = findings_by_id.get(FindingId(finding_model.id))
        if matching_finding is None:
            continue

        finding_model.status = matching_finding.status
        _append_new_feedback(finding_model, matching_finding)


def _append_new_feedback(finding_model: FindingModel, finding: Finding) -> None:
    persisted_ids = {feedback_model.id for feedback_model in finding_model.feedback}
    for entry in finding.feedback:
        if entry.id in persisted_ids:
            continue
        finding_model.feedback.append(
            FindingFeedbackModel(
                id=entry.id,
                verdict=entry.verdict,
                comment=entry.comment,
                user_id=entry.user_id,
                created_at=entry.created_at,
            )
        )


def _file_to_domain(model: ReviewFileModel) -> ReviewFile:
    return ReviewFile(
        id=ReviewFileId(model.id),
        path=model.path,
        previous_path=model.previous_path,
        change_type=model.change_type,
        language=model.language,
        added_lines=model.added_lines,
        removed_lines=model.removed_lines,
        hunks=[_hunk_to_domain(hunk_model) for hunk_model in model.hunks],
    )


def _hunk_to_domain(model: ReviewHunkModel) -> ReviewHunk:
    return ReviewHunk(
        id=ReviewHunkId(model.id),
        old_start=model.old_start,
        old_lines=model.old_lines,
        new_start=model.new_start,
        new_lines=model.new_lines,
        header=model.header,
        patch_text=model.patch_text,
    )


def _finding_to_domain(model: FindingModel) -> Finding:
    return Finding(
        id=FindingId(model.id),
        file_path=model.file_path,
        line_start=model.line_start,
        line_end=model.line_end,
        side=model.side,
        severity=model.severity,
        category=model.category,
        title=model.title,
        body_markdown=model.body_markdown,
        dedup_key=model.dedup_key,
        producer=model.producer,
        producer_name=model.producer_name,
        rule_id=model.rule_id,
        suggested_patch=model.suggested_patch,
        confidence=model.confidence,
        status=model.status,
        evidence=[
            Evidence(
                kind=evidence_model.kind,
                file_path=evidence_model.file_path,
                snippet=evidence_model.snippet,
                line_start=evidence_model.line_start,
                line_end=evidence_model.line_end,
            )
            for evidence_model in model.evidence
        ],
        feedback=[
            FindingFeedback(
                id=FindingFeedbackId(feedback_model.id),
                verdict=feedback_model.verdict,
                created_at=feedback_model.created_at,
                user_id=UserId(feedback_model.user_id)
                if feedback_model.user_id is not None
                else None,
                comment=feedback_model.comment,
            )
            for feedback_model in model.feedback
        ],
    )


def _file_to_model(file: ReviewFile) -> ReviewFileModel:
    return ReviewFileModel(
        id=file.id,
        path=file.path,
        previous_path=file.previous_path,
        change_type=file.change_type,
        language=file.language,
        added_lines=file.added_lines,
        removed_lines=file.removed_lines,
        hunks=[_hunk_to_model(hunk) for hunk in file.hunks],
    )


def _hunk_to_model(hunk: ReviewHunk) -> ReviewHunkModel:
    return ReviewHunkModel(
        id=hunk.id,
        old_start=hunk.old_start,
        old_lines=hunk.old_lines,
        new_start=hunk.new_start,
        new_lines=hunk.new_lines,
        header=hunk.header,
        patch_text=hunk.patch_text,
    )


def _finding_to_model(finding: Finding) -> FindingModel:
    return FindingModel(
        id=finding.id,
        file_path=finding.file_path,
        line_start=finding.line_start,
        line_end=finding.line_end,
        side=finding.side,
        severity=finding.severity,
        category=finding.category,
        title=finding.title,
        body_markdown=finding.body_markdown,
        suggested_patch=finding.suggested_patch,
        confidence=finding.confidence,
        producer=finding.producer,
        producer_name=finding.producer_name,
        rule_id=finding.rule_id,
        status=finding.status,
        dedup_key=finding.dedup_key,
        evidence=[
            FindingEvidenceModel(
                id=uuid4(),
                kind=evidence.kind,
                file_path=evidence.file_path,
                line_start=evidence.line_start,
                line_end=evidence.line_end,
                snippet=evidence.snippet,
            )
            for evidence in finding.evidence
        ],
    )
