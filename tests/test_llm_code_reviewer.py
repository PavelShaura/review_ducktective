import json
from collections.abc import (
    Sequence,
)
from typing import (
    Any,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.core.diff.value_objects import (
    ChangeType,
)
from ducktective.core.exceptions import (
    LlmOutputError,
)
from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmResponse,
    LlmUsage,
    ModelRequirements,
    ToolSpec,
)
from ducktective.core.review.drafts import (
    FindingDraft,
)
from ducktective.core.review.entities import (
    ReviewFile,
    ReviewHunk,
)
from ducktective.core.review.reviewers import (
    ReviewerKind,
)
from ducktective.core.review.value_objects import (
    FindingCategory,
    Severity,
)
from ducktective.core.types import (
    ReviewFileId,
    ReviewHunkId,
)
from ducktective.llm.code_reviewer import (
    DEFAULT_ATTEMPTS,
    LlmCodeReviewer,
    system_prompt,
)
from tests.fakes import (
    FakeLlmClient,
)


VALID_PAYLOAD = {
    "findings": [
        {
            "line_start": 11,
            "line_end": 11,
            "severity": "major",
            "category": "performance",
            "title": "Запрос в цикле",
            "body": "Вызов выполняется на каждой итерации",
            "code_fragment": "result = self._compute()",
            "anchor_symbol": "ReportBuilder.build",
            "confidence": 0.8,
            "evidence": [{"snippet": "result = self._compute()", "line_start": 11, "line_end": 11}],
        }
    ]
}


def build_file() -> ReviewFile:
    return ReviewFile(
        id=ReviewFileId(uuid4()),
        path="app/service.py",
        previous_path=None,
        change_type=ChangeType.MODIFIED,
        language="python",
        added_lines=2,
        removed_lines=1,
        hunks=[
            ReviewHunk(
                id=ReviewHunkId(uuid4()),
                old_start=10,
                old_lines=2,
                new_start=10,
                new_lines=3,
                header="class ReportBuilder:",
                patch_text="@@ -10,2 +10,3 @@\n+        result = self._compute()\n",
            )
        ],
    )


async def review_with(content: str) -> list[FindingDraft]:
    file = build_file()
    reviewer = LlmCodeReviewer(FakeLlmClient(content))
    result = await reviewer.review_file(
        file,
        patch_text=file.to_unified_patch(),
        requirements=ModelRequirements(),
    )
    return result.drafts


async def test_plain_json_is_parsed() -> None:
    drafts = await review_with(json.dumps(VALID_PAYLOAD))

    assert len(drafts) == 1
    assert drafts[0].severity is Severity.MAJOR
    assert drafts[0].category is FindingCategory.PERFORMANCE
    assert drafts[0].anchor_symbol == "ReportBuilder.build"


async def test_json_wrapped_in_markdown_is_parsed() -> None:
    content = f"Вот результат:\n```json\n{json.dumps(VALID_PAYLOAD)}\n```\nГотово."

    drafts = await review_with(content)

    assert len(drafts) == 1


async def test_json_surrounded_by_prose_is_parsed() -> None:
    content = f"Sure! {json.dumps(VALID_PAYLOAD)} Hope that helps."

    drafts = await review_with(content)

    assert len(drafts) == 1


async def test_empty_findings_are_valid() -> None:
    drafts = await review_with('{"findings": []}')

    assert drafts == []


async def test_response_without_json_raises() -> None:
    with pytest.raises(LlmOutputError):
        await review_with("Мне нечего добавить по этому файлу")


async def test_response_with_wrong_schema_raises() -> None:
    with pytest.raises(LlmOutputError):
        await review_with('{"findings": [{"severity": "unknown"}]}')


async def test_prompt_contains_file_metadata_and_patch() -> None:
    file = build_file()
    client = FakeLlmClient('{"findings": []}')
    reviewer = LlmCodeReviewer(client)

    await reviewer.review_file(
        file,
        patch_text=file.to_unified_patch(),
        requirements=ModelRequirements(),
    )

    user_message = client.calls[0][1].content
    assert "app/service.py" in user_message
    assert "Language: python" in user_message
    assert "@@ -10,2 +10,3 @@" in user_message


async def test_reviewer_speaks_with_the_prompt_of_its_specialisation() -> None:
    file = build_file()
    client = FakeLlmClient('{"findings": []}')
    reviewer = LlmCodeReviewer(client, kind=ReviewerKind.SECURITY)

    await reviewer.review_file(
        file,
        patch_text=file.to_unified_patch(),
        requirements=ModelRequirements(),
    )

    assert reviewer.name == "reviewer:security"
    assert "security engineer" in client.calls[0][0].content


@pytest.mark.parametrize("kind", list(ReviewerKind))
def test_every_prompt_carries_the_common_part(kind: ReviewerKind) -> None:
    """Рубрика severity и формат ответа одинаковы у всех четверых."""
    prompt = system_prompt(kind)

    assert prompt.startswith("You are")
    assert "Severity rubric" in prompt
    assert "Return JSON only" in prompt


@pytest.mark.parametrize("kind", list(ReviewerKind))
def test_prompts_say_nothing_about_linters(kind: ReviewerKind) -> None:
    """Территория линтера в ревью не обсуждается — ни запретом, ни разрешением."""
    prompt = system_prompt(kind).lower()

    assert "linter" not in prompt
    assert "type checker" not in prompt


def test_focus_differs_between_reviewers() -> None:
    prompts = {system_prompt(kind) for kind in ReviewerKind}

    assert len(prompts) == len(ReviewerKind)


class FlakyLlmClient:
    """Клиент, отвечающий прозой, пока его не переспросят."""

    def __init__(self, *, failures: int) -> None:
        self.failures = failures
        self.calls: list[list[LlmMessage]] = []

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        requirements: ModelRequirements,
        json_schema: dict[str, Any] | None = None,
        tools: Sequence[ToolSpec] | None = None,
    ) -> LlmResponse:
        self.calls.append(messages)
        content = (
            "Конечно! Вот мой разбор кода."
            if len(self.calls) <= self.failures
            else '{"findings": []}'
        )
        return LlmResponse(
            content=content,
            model="fake-model",
            provider="fake",
            usage=LlmUsage(input_tokens=10, output_tokens=5),
        )


async def test_unparseable_answer_is_retried() -> None:
    """Длинная подсказка сбивает модель на прозу — терять из-за этого файл незачем."""
    client = FlakyLlmClient(failures=1)

    result = await LlmCodeReviewer(client).review_file(
        build_file(),
        patch_text=build_file().to_unified_patch(),
        requirements=ModelRequirements(),
    )

    assert result.drafts == []
    assert len(client.calls) == 2


async def test_retry_tells_the_model_what_went_wrong() -> None:
    client = FlakyLlmClient(failures=1)

    await LlmCodeReviewer(client).review_file(
        build_file(),
        patch_text=build_file().to_unified_patch(),
        requirements=ModelRequirements(),
    )

    correction = client.calls[1][-1].content
    assert "JSON" in correction


async def test_attempts_are_not_endless() -> None:
    client = FlakyLlmClient(failures=10)

    with pytest.raises(LlmOutputError):
        await LlmCodeReviewer(client).review_file(
            build_file(),
            patch_text=build_file().to_unified_patch(),
            requirements=ModelRequirements(),
        )

    assert len(client.calls) == DEFAULT_ATTEMPTS
