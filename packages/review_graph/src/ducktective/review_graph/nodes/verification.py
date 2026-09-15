from typing import (
    TYPE_CHECKING,
    Any,
)

from langgraph.runtime import (
    Runtime,
)

from ducktective.core.review.trace import (
    trace,
)
from ducktective.core.review.value_objects import (
    ReviewLanguage,
)
from ducktective.core.review.verification import (
    build_verified_finding,
    collect_evidence,
    has_confirmable_evidence,
    has_proof_of_external_claim,
)
from ducktective.review_graph.nodes.reporting import (
    report_stage,
)
from ducktective.review_graph.state import (
    MergedDraft,
    ReviewGraphState,
    ReviewRuntimeContext,
)


if TYPE_CHECKING:
    from ducktective.core.review.entities import (
        Finding,
    )


async def verify(
    state: ReviewGraphState,
    *,
    runtime: Runtime[ReviewRuntimeContext],
) -> dict[str, Any]:
    """Отсеивает то, что не подтверждается кодом, и называет причину.

    Причины считаются раздельно: находка не о том коде, который меняли; цитата
    не найдена ни в патче, ни в показанном окружении; такая находка уже есть.
    Первое лечится промптом, второе — контекстом, третье не лечится вовсе.

    Вытесненный при слиянии черновик получает ту же классификацию: назвать его
    дублем, когда он и сам не прошёл бы проверку, значило бы прятать причину.
    """
    findings: list[Finding] = []
    outside_diff = 0
    without_evidence = 0
    unproven_claim = 0
    duplicates = 0

    for item in state.merged:
        if not _covers_changed_lines(item):
            outside_diff += 1
            continue

        evidence = collect_evidence(
            item.draft,
            item.file.to_unified_patch(),
            item.context,
            shown=item.shown,
        )
        if not evidence:
            without_evidence += 1
            continue

        if not has_proof_of_external_claim(item.draft, evidence, shown=item.shown):
            unproven_claim += 1
            continue

        finding = build_verified_finding(
            item.draft,
            item.file,
            producer_name=item.reviewer_name,
            context=item.context,
            shown=item.shown,
        )
        if finding is None:
            without_evidence += 1
            continue

        findings.append(finding)

    for item in state.displaced:
        if not _covers_changed_lines(item):
            outside_diff += 1
        elif not has_confirmable_evidence(item.draft, item.file, item.context, shown=item.shown):
            without_evidence += 1
        else:
            duplicates += 1

    await report_stage(
        runtime,
        _describe_verification(
            runtime.context.language,
            confirmed=len(findings),
            outside_diff=outside_diff,
            without_evidence=without_evidence,
            unproven_claim=unproven_claim,
            duplicates=duplicates,
        ),
    )
    return {
        "findings": tuple(findings),
        "discarded_outside_diff": outside_diff,
        "discarded_without_evidence": without_evidence,
        "discarded_unproven_claim": unproven_claim,
        "discarded_as_duplicate": duplicates,
    }


def _describe_verification(
    language: ReviewLanguage,
    *,
    confirmed: int,
    outside_diff: int,
    without_evidence: int,
    unproven_claim: int,
    duplicates: int,
) -> str:
    """Итог проверки с разбивкой по причинам.

    Общее «отброшено 24» не говорит, что чинить: цитата мимо кода лечится
    промптом, находка вне диффа — привязкой строк, дубли не лечатся вовсе.
    """
    reasons = [
        (outside_diff, "reason_outside_diff"),
        (without_evidence, "reason_no_evidence"),
        (unproven_claim, "reason_unproven"),
        (duplicates, "reason_duplicates"),
    ]
    named = ", ".join(f"{trace(language, key)} {count}" for count, key in reasons if count)
    if not named:
        return trace(language, "verify_clean", confirmed=confirmed)
    return trace(language, "verify_dropped", confirmed=confirmed, named=named)


def _covers_changed_lines(item: MergedDraft) -> bool:
    return item.file.covers_line(item.draft.line_start)
