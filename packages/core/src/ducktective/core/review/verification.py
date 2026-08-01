from dataclasses import (
    dataclass,
)
from uuid import (
    uuid4,
)

from ducktective.core.retrieval.context import (
    DiffContext,
)
from ducktective.core.review.dedup import (
    build_dedup_key,
)
from ducktective.core.review.drafts import (
    FindingDraft,
)
from ducktective.core.review.entities import (
    Evidence,
    Finding,
    ReviewFile,
)
from ducktective.core.review.value_objects import (
    EvidenceKind,
    FindingProducer,
    FindingStatus,
)
from ducktective.core.types import (
    FindingId,
)


WHITESPACE = " \t\r\n"


@dataclass(frozen=True, kw_only=True)
class _EvidenceSource:
    """Текст, в котором ищется цитата, вместе с его происхождением."""

    normalized_text: str
    kind: EvidenceKind
    file_path: str
    line_start: int
    line_end: int


def build_verified_finding(
    draft: FindingDraft,
    file: ReviewFile,
    *,
    producer_name: str,
    producer: FindingProducer = FindingProducer.LLM,
    context: DiffContext | None = None,
) -> Finding | None:
    """Превращает черновик в находку, отбраковывая недостоверные.

    Находка без подтверждённой цитаты не создаётся: это типичный признак
    выдуманного контекста (D-008). Принадлежность строки диффу проверяется
    отдельно и раньше, чтобы различать причины отбраковки.
    """
    evidence = collect_evidence(draft, file.to_unified_patch(), context)
    if not evidence:
        return None

    return Finding(
        id=FindingId(uuid4()),
        file_path=file.path,
        line_start=draft.line_start,
        line_end=draft.line_end,
        side=draft.side,
        severity=draft.severity,
        category=draft.category,
        title=draft.title,
        body_markdown=draft.body_markdown,
        dedup_key=build_dedup_key(
            category=draft.category,
            rule_id=None,
            symbol_name=draft.anchor_symbol,
            file_path=file.path,
            code_fragment=draft.code_fragment or draft.title,
        ),
        producer=producer,
        producer_name=producer_name,
        suggested_patch=draft.suggested_patch,
        confidence=draft.confidence,
        status=FindingStatus.VERIFIED,
        evidence=evidence,
    )


def collect_evidence(
    draft: FindingDraft,
    patch_text: str,
    context: DiffContext | None = None,
) -> list[Evidence]:
    """Оставляет только те цитаты, которые действительно существуют.

    Искать их приходится и в патче, и в показанном окружении: получив контекст,
    модель ссылается на вызывающий код, и такая ссылка — самое ценное, что она
    может сказать. Проверка от этого не слабеет, потому что окружение — это
    ровно то, что мы ей показали, а не то, что она придумала.
    """
    candidates = [item.snippet for item in draft.evidence]
    if draft.code_fragment:
        candidates.append(draft.code_fragment)

    sources = _evidence_sources(draft, patch_text, context)

    confirmed: list[Evidence] = []
    seen: set[str] = set()
    for snippet in candidates:
        normalized = _normalize(snippet)
        if not normalized or normalized in seen:
            continue

        source = next((item for item in sources if normalized in item.normalized_text), None)
        if source is None:
            continue

        seen.add(normalized)
        confirmed.append(
            Evidence(
                kind=source.kind,
                file_path=source.file_path,
                snippet=snippet.strip(),
                line_start=source.line_start,
                line_end=source.line_end,
            )
        )
    return confirmed


def has_confirmable_evidence(
    draft: FindingDraft,
    file: ReviewFile,
    context: DiffContext | None = None,
) -> bool:
    """Есть ли у черновика хоть одна подтверждаемая цитата.

    Нужно узлу слияния: из двух черновиков с одним ключом дедупликации
    выживать должен тот, что переживёт проверку, иначе слияние роняет
    находку вместо дубля.
    """
    return bool(collect_evidence(draft, file.to_unified_patch(), context))


def _evidence_sources(
    draft: FindingDraft,
    patch_text: str,
    context: DiffContext | None,
) -> list[_EvidenceSource]:
    """Тексты, в которых цитата считается подтверждённой.

    Патч идёт первым: если строка встречается и в нём, и в окружении, находка
    относится к изменению, а не к соседнему коду.
    """
    sources = [
        _EvidenceSource(
            normalized_text=_normalize(patch_text),
            kind=EvidenceKind.QUOTED_CODE,
            file_path=draft.file_path,
            line_start=draft.line_start,
            line_end=draft.line_end,
        )
    ]
    sources.extend(
        _EvidenceSource(
            normalized_text=_normalize(piece.text),
            kind=EvidenceKind.RETRIEVED_CHUNK,
            file_path=piece.path,
            line_start=piece.start_line,
            line_end=piece.end_line,
        )
        for piece in (context.pieces if context else ())
    )
    return sources


def _normalize(text: str) -> str:
    return " ".join(text.split()).strip(WHITESPACE)
