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
)
from ducktective.core.llm.ports import (
    LlmClient,
)
from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmRole,
    ModelRequirements,
)
from ducktective.core.review.drafts import (
    EvidenceDraft,
    FindingDraft,
)
from ducktective.core.review.entities import (
    ReviewFile,
)
from ducktective.core.review.ports import (
    FileReviewResult,
)
from ducktective.core.review.value_objects import (
    FindingCategory,
    Severity,
)
from ducktective.llm.schemas import (
    FindingPayload,
    ReviewPayload,
)


PROMPTS_DIRECTORY = Path(__file__).parent / "prompts"
SINGLE_PASS_PROMPT_FILE = "single_pass_review.md"
JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@cache
def load_prompt(file_name: str) -> str:
    return (PROMPTS_DIRECTORY / file_name).read_text(encoding="utf-8")


class LlmCodeReviewer:
    """Ревьюер одного файла: один вызов модели на файл.

    Промежуточный вариант до появления графа со специализированными узлами:
    один промпт покрывает все категории находок.
    """

    name = "reviewer:single-pass"

    def __init__(self, llm_client: LlmClient) -> None:
        self._llm_client = llm_client

    async def review_file(
        self,
        file: ReviewFile,
        *,
        patch_text: str,
        requirements: ModelRequirements,
    ) -> FileReviewResult:
        messages = [
            LlmMessage(role=LlmRole.SYSTEM, content=load_prompt(SINGLE_PASS_PROMPT_FILE)),
            LlmMessage(role=LlmRole.USER, content=_build_user_message(file, patch_text)),
        ]
        response = await self._llm_client.complete(
            messages,
            requirements=requirements,
            json_schema=ReviewPayload.model_json_schema(),
        )
        payload = _parse_payload(response.content)

        return FileReviewResult(
            drafts=[_to_draft(finding, file.path) for finding in payload.findings],
            usage=response.usage,
            model=response.model,
            is_cache_hit=response.is_cache_hit,
        )


def _build_user_message(file: ReviewFile, patch_text: str) -> str:
    language = file.language or "unknown"
    return (
        f"File: {file.path}\n"
        f"Language: {language}\n"
        f"Change type: {file.change_type.value}\n\n"
        f"Unified diff:\n\n{patch_text}"
    )


def _parse_payload(content: str) -> ReviewPayload:
    raw_json = _extract_json(content)
    try:
        return ReviewPayload.model_validate_json(raw_json)
    except ValidationError as error:
        raise LlmOutputError(f"Ответ модели не соответствует схеме: {error}") from error


def _extract_json(content: str) -> str:
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
        raise LlmOutputError("В ответе модели нет JSON-объекта")

    candidate = stripped[first_brace : last_brace + 1]
    try:
        json.loads(candidate)
    except json.JSONDecodeError as error:
        raise LlmOutputError(f"Не удалось разобрать JSON из ответа модели: {error}") from error
    return candidate


def _to_draft(payload: FindingPayload, file_path: str) -> FindingDraft:
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
