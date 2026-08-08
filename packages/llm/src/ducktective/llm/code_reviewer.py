import json
import re
from functools import (
    cache,
)
from pathlib import (
    Path,
)

from pydantic import (
    ValidationError,
)

from ducktective.core.diff.value_objects import (
    DiffSide,
)
from ducktective.core.exceptions import (
    LlmOutputError,
    LlmOutputTruncatedError,
)
from ducktective.core.llm.ports import (
    LlmClient,
)
from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmResponse,
    LlmRole,
    ModelRequirements,
)
from ducktective.core.retrieval.context import (
    ContextOrigin,
    DiffContext,
)
from ducktective.core.retrieval.navigation import (
    CodeNavigator,
)
from ducktective.core.review.drafts import (
    EvidenceDraft,
    FindingDraft,
)
from ducktective.core.review.entities import (
    ReviewFile,
)
from ducktective.core.review.investigation import (
    InvestigationSink,
)
from ducktective.core.review.ports import (
    FileReviewResult,
)
from ducktective.core.review.reviewers import (
    ReviewMode,
    reviewer_name,
)
from ducktective.core.review.value_objects import (
    FindingCategory,
    Severity,
)
from ducktective.llm.schemas import (
    FindingPayload,
    ReviewPayload,
)


DEFAULT_ATTEMPTS = 2

ORIGIN_TITLES = {
    ContextOrigin.CHANGED_SYMBOL: "Full definitions of the changed symbols",
    ContextOrigin.CALLEE: "Contracts of what the changed code calls",
    ContextOrigin.CALLER: "Callers of the changed code — what may break",
    ContextOrigin.SIMILAR: "Similar places elsewhere in the project",
}

PROMPTS_DIRECTORY = Path(__file__).parent / "prompts"
COMMON_PROMPT_FILE = "review_common.md"
REVIEWER_PROMPT_FILE = "reviewer.md"
AGENT_PROMPT_FILE = "reviewer_agent.md"
PROMPT_SET_NAME = "reviewer-v1"
JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@cache
def load_prompt(file_name: str) -> str:
    return (PROMPTS_DIRECTORY / file_name).read_text(encoding="utf-8")


@cache
def system_prompt(*, with_tools: bool = False) -> str:
    """Подсказка ревьюера: что искать, как расследовать, как ответить.

    Части три и склеиваются они в одном месте. Перечень того, что искать, —
    один на оба режима: ревьюер один (D-022), и разными их делает способ
    добывать сведения, а не то, что они ищут. Правила доказательств, рубрика
    severity и формат ответа тоже общие — копия этого текста разъехалась бы
    на первой правке, и разница в результатах перестала бы быть объяснимой.
    """
    parts = [load_prompt(REVIEWER_PROMPT_FILE)]
    if with_tools:
        parts.append(load_prompt(AGENT_PROMPT_FILE))
    parts.append(load_prompt(COMMON_PROMPT_FILE))
    return "\n\n".join(parts)


class LlmCodeReviewer:
    """Ревьюер одного файла: один вызов модели на файл.

    Работает по тому, что показали заранее: патч и собранное окружение.
    Запасной путь для файла, который вместе с диалогом инструментов не влезет
    в окно модели, — и единственный, когда инструментов нет вовсе.
    """

    def __init__(
        self,
        llm_client: LlmClient,
        *,
        attempts: int = DEFAULT_ATTEMPTS,
    ) -> None:
        self._llm_client = llm_client
        self._attempts = attempts
        self.name = reviewer_name(ReviewMode.SINGLE_PASS)

    async def _ask(
        self,
        messages: list[LlmMessage],
        requirements: ModelRequirements,
    ) -> tuple[LlmResponse, ReviewPayload]:
        """Спрашивает модель, пока та не ответит разбираемым JSON.

        Модель иногда сбивается на прозу — тем чаще, чем длиннее подсказка.
        Терять из-за этого ревью целого файла незачем: повтор с указанием
        на ошибку обходится дешевле, чем пропущенная находка.
        """
        schema = ReviewPayload.model_json_schema()
        last_error: LlmOutputError | None = None

        for attempt in range(self._attempts):
            response = await self._llm_client.complete(
                messages if attempt == 0 else [*messages, _correction(last_error)],
                requirements=requirements,
                json_schema=schema,
            )
            try:
                return response, parse_payload(response.content, model=response.model)
            except LlmOutputError as error:
                last_error = (
                    _truncated_error(response.model, requirements)
                    if response.is_truncated
                    else error
                )

        raise last_error if last_error else LlmOutputError("Модель не вернула ответ")

    async def review_file(
        self,
        file: ReviewFile,
        *,
        patch_text: str,
        requirements: ModelRequirements,
        context: DiffContext | None = None,
        navigator: CodeNavigator | None = None,
        sink: InvestigationSink | None = None,
    ) -> FileReviewResult:
        """Читает файл одним обращением к модели.

        Ни инструменты, ни лента хода не используются: этот ревьюер работает
        по тому, что ему показали, и рассказывать по дороге ему нечего.
        Параметры есть, потому что они есть у порта, и молчаливо принять их
        честнее, чем требовать от вызывающего знать, кому что нужно.
        """
        messages = [
            LlmMessage(role=LlmRole.SYSTEM, content=system_prompt()),
            LlmMessage(role=LlmRole.USER, content=build_user_message(file, patch_text, context)),
        ]
        response, payload = await self._ask(messages, requirements)

        return FileReviewResult(
            drafts=[to_draft(finding, file.path) for finding in payload.findings],
            usage=response.usage,
            model=response.model,
            is_cache_hit=response.is_cache_hit,
        )


def _truncated_error(model: str, requirements: ModelRequirements) -> LlmOutputError:
    """Обрыв на лимите — не то же самое, что сбившаяся с формата модель.

    Разница видна только по finish_reason, а чинится по-разному: лимитом,
    бюджетом контекста или моделью, не тратящей выход на размышления.

    Лимит назван лимитом ответа: рядом в отчёте стоит окно модели, и два
    числа в токенах, из которых одно безымянное, читаются как одно и то же.
    """
    return LlmOutputTruncatedError(
        f"Модель {model} исчерпала лимит ответа в {requirements.max_output_tokens} токенов",
        model=model,
    )


def _correction(error: LlmOutputError | None) -> LlmMessage:
    """Уточняющее сообщение после неразобранного ответа."""
    return LlmMessage(
        role=LlmRole.USER,
        content=(
            "Your previous answer could not be parsed"
            f"{f': {error}' if error else ''}. "
            "Reply with a single JSON object matching the schema and nothing else: "
            "no prose, no markdown fences, no explanation."
        ),
    )


def build_user_message(
    file: ReviewFile,
    patch_text: str,
    context: DiffContext | None,
) -> str:
    parts = [
        f"File: {file.path}",
        f"Language: {file.language or 'unknown'}",
        f"Change type: {file.change_type.value}",
        "",
        f"Unified diff:\n\n{patch_text}",
    ]

    if context is not None and not context.is_empty:
        parts.extend(["", _render_context(context)])

    return "\n".join(parts)


def _render_context(context: DiffContext) -> str:
    """Раскладывает контекст по назначению фрагментов.

    Модель должна понимать не только что перед ней за код, но и почему он
    показан: вызываемое читается как контракт, вызывающее — как список того,
    что сломается, похожее — как принятый в проекте образец.
    """
    sections = [
        "## Repository context",
        "",
        "Code below is NOT part of the diff. Use it to judge the change; never report",
        "problems in it. Quoting it as evidence is allowed.",
    ]

    for origin in ContextOrigin:
        pieces = context.of_origin(origin)
        if not pieces:
            continue

        sections.extend(["", f"### {ORIGIN_TITLES[origin]}"])
        for piece in pieces:
            name = piece.qualified_name or piece.path
            sections.extend(
                [
                    "",
                    f"{name} ({piece.location})",
                    "```",
                    piece.text.strip(),
                    "```",
                ]
            )

    return "\n".join(sections)


def parse_payload(content: str, *, model: str) -> ReviewPayload:
    raw_json = _extract_json(content, model=model)
    try:
        return ReviewPayload.model_validate_json(raw_json)
    except ValidationError as error:
        raise LlmOutputError(
            f"Ответ модели не соответствует схеме: {error}",
            model=model,
        ) from error


def _extract_json(content: str, *, model: str) -> str:
    """Достаёт JSON из ответа.

    Модели без строгого structured output регулярно оборачивают результат
    в markdown-блок или добавляют пояснения вокруг него.
    """
    stripped = content.strip()
    if stripped.startswith("{"):
        return stripped

    block_match = JSON_BLOCK_PATTERN.search(stripped)
    if block_match is not None:
        return block_match.group(1)

    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace == -1 or last_brace <= first_brace:
        raise LlmOutputError("В ответе модели нет JSON-объекта", model=model)

    candidate = stripped[first_brace : last_brace + 1]
    try:
        json.loads(candidate)
    except json.JSONDecodeError as error:
        raise LlmOutputError(
            f"Не удалось разобрать JSON из ответа модели: {error}",
            model=model,
        ) from error
    return candidate


def to_draft(payload: FindingPayload, file_path: str) -> FindingDraft:
    return FindingDraft(
        file_path=file_path,
        line_start=payload.line_start,
        line_end=max(payload.line_end, payload.line_start),
        side=DiffSide.NEW,
        severity=Severity(payload.severity),
        category=FindingCategory(payload.category),
        title=payload.title,
        body_markdown=payload.body,
        anchor_symbol=payload.anchor_symbol,
        code_fragment=payload.code_fragment,
        suggested_patch=payload.suggested_patch,
        confidence=payload.confidence,
        evidence=[
            EvidenceDraft(
                file_path=file_path,
                snippet=item.snippet,
                line_start=item.line_start,
                line_end=item.line_end,
            )
            for item in payload.evidence
        ],
    )
