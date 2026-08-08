from typing import (
    Any,
)

from langgraph.runtime import (
    Runtime,
)

from ducktective.core.review.dedup import (
    build_dedup_key,
)
from ducktective.core.review.value_objects import (
    SEVERITY_RANK,
)
from ducktective.core.review.verification import (
    has_confirmable_evidence,
)
from ducktective.review_graph.nodes.reporting import (
    report_stage,
)
from ducktective.review_graph.state import (
    MergedDraft,
    ReviewGraphState,
    ReviewRuntimeContext,
)


async def aggregate(
    state: ReviewGraphState,
    *,
    runtime: Runtime[ReviewRuntimeContext],
) -> dict[str, Any]:
    """Сводит черновики всех ревьюеров в один список без дублей.

    Из группы с одним ключом дедупликации выживает не первый пришедший,
    а тот, кто переживёт проверку: иначе черновик с выдуманной цитатой
    вытесняет своего достоверного двойника, и находка теряется совсем.

    Проигравшие не выбрасываются, а едут дальше: причину, по которой черновик
    не дошёл до человека, называет узел проверки, и называет её один на всех.
    """
    survivors: dict[str, MergedDraft] = {}
    displaced: list[MergedDraft] = []
    proposed = 0

    for result in state.results:
        for draft in result.drafts:
            proposed += 1
            candidate = MergedDraft(
                draft=draft,
                file=result.file,
                context=result.context,
                shown=result.shown,
                reviewer_name=result.reviewer_name,
            )
            key = build_dedup_key(
                category=draft.category,
                rule_id=None,
                symbol_name=draft.anchor_symbol,
                file_path=result.file.path,
                code_fragment=draft.code_fragment or draft.title,
            )

            previous = survivors.get(key)
            if previous is None:
                survivors[key] = candidate
                continue

            if _survival_rank(candidate) > _survival_rank(previous):
                survivors[key] = candidate
                displaced.append(previous)
            else:
                displaced.append(candidate)

    await report_stage(
        runtime,
        f"Свожу черновики: предложено {proposed}, осталось {len(survivors)}",
    )
    return {
        "merged": tuple(survivors.values()),
        "displaced": tuple(displaced),
        "proposed": proposed,
    }


def _survival_rank(item: MergedDraft) -> tuple[bool, bool, int]:
    """Насколько черновик пригоден к публикации.

    Порядок признаков — порядок причин отбраковки в узле проверки:
    привязка к изменённым строкам, наличие подтверждаемой цитаты, и лишь
    затем уровень.
    """
    return (
        item.file.covers_line(item.draft.line_start),
        has_confirmable_evidence(item.draft, item.file, item.context, shown=item.shown),
        SEVERITY_RANK[item.draft.severity],
    )
