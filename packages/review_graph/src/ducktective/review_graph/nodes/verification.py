from typing import (
    TYPE_CHECKING,
    Any,
)

from ducktective.core.review.verification import (
    build_verified_finding,
    has_confirmable_evidence,
)
from ducktective.review_graph.state import (
    MergedDraft,
    ReviewGraphState,
)


if TYPE_CHECKING:
    from ducktective.core.review.entities import (
        Finding,
    )


def verify(state: ReviewGraphState) -> dict[str, Any]:
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
    duplicates = 0

    for item in state.merged:
        if not _covers_changed_lines(item):
            outside_diff += 1
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

    return {
        "findings": tuple(findings),
        "discarded_outside_diff": outside_diff,
        "discarded_without_evidence": without_evidence,
        "discarded_as_duplicate": duplicates,
    }


def _covers_changed_lines(item: MergedDraft) -> bool:
    return item.file.covers_line(item.draft.line_start)
