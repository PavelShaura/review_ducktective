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
    LlmContextOverflowError,
    ReviewInterruptedError,
)
from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmResponse,
    LlmRole,
    LlmUsage,
    ModelRequirements,
    ToolCall,
    ToolSpec,
)
from ducktective.core.retrieval.navigation import (
    CodeFragment,
    FragmentRole,
    NavigationAnswer,
    NavigationSource,
    ReferenceRelation,
)
from ducktective.core.review.entities import (
    ReviewFile,
    ReviewHunk,
    RunDiff,
)
from ducktective.core.review.investigation import (
    InvestigationStep,
    StepKind,
)
from ducktective.core.review.ports import (
    FileReviewResult,
    ReviewSupport,
)
from ducktective.core.types import (
    ReviewFileId,
    ReviewHunkId,
)
from ducktective.llm.agentic_reviewer import (
    AgenticCodeReviewer,
)
from ducktective.llm.code_reviewer import (
    LlmCodeReviewer,
)
from tests.fakes import (
    FakeLlmClient,
    StubNavigator,
)


FINDINGS_JSON = json.dumps(
    {
        "findings": [
            {
                "line_start": 11,
                "line_end": 11,
                "severity": "major",
                "category": "correctness",
                "title": "Проверка дублей убрана",
                "body": "Вызывающие рассчитывают на отказ при повторе",
                "code_fragment": "result = self._compute()",
                "anchor_symbol": "ReportBuilder.build",
                "confidence": 0.8,
                "evidence": [
                    {"snippet": "result = self._compute()", "line_start": 11, "line_end": 11}
                ],
            }
        ]
    }
)
EMPTY_JSON = '{"findings": []}'

LOCAL_FINDING_JSON = json.dumps(
    {
        "findings": [
            {
                "line_start": 11,
                "line_end": 11,
                "severity": "minor",
                "category": "correctness",
                "title": "Значение считается дважды",
                "body": "Результат вычисляется повторно в той же строке",
                "code_fragment": "result = self._compute()",
                "anchor_symbol": "ReportBuilder.build",
                "confidence": 0.6,
                "evidence": [
                    {"snippet": "result = self._compute()", "line_start": 11, "line_end": 11}
                ],
            }
        ]
    }
)


def build_file() -> ReviewFile:
    return ReviewFile(
        id=ReviewFileId(uuid4()),
        path="app/service.py",
        previous_path=None,
        change_type=ChangeType.MODIFIED,
        language="python",
        added_lines=1,
        removed_lines=0,
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


class ScriptedLlmClient:
    """Клиент, отвечающий по заранее написанному сценарию."""

    def __init__(self, responses: list[LlmResponse]) -> None:
        self.responses = responses
        self.calls: list[list[LlmMessage]] = []
        self.offered_tools: list[tuple[str, ...]] = []
        self.schemas: list[dict[str, Any] | None] = []
        self.requirements: list[ModelRequirements] = []

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        requirements: ModelRequirements,
        json_schema: dict[str, Any] | None = None,
        tools: Sequence[ToolSpec] | None = None,
    ) -> LlmResponse:
        self.calls.append(list(messages))
        self.offered_tools.append(tuple(tool.name for tool in tools or ()))
        self.schemas.append(json_schema)
        self.requirements.append(requirements)
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


def answer(
    content: str = "",
    *,
    calls: tuple[ToolCall, ...] = (),
    truncated: bool = False,
    input_tokens: int = 100,
    context_window: int = 0,
) -> LlmResponse:
    return LlmResponse(
        content=content,
        model="fake-model",
        provider="fake",
        usage=LlmUsage(input_tokens=input_tokens, output_tokens=50),
        tool_calls=calls,
        is_truncated=truncated,
        context_window=context_window,
    )


def call(name: str = "find_callers", arguments: str = '{"name": "build"}') -> ToolCall:
    return ToolCall(id="call_1", name=name, arguments=arguments)


class FakeNavigator(StubNavigator):
    source = NavigationSource.INDEX

    def __init__(self, *, empty: bool = False, text: str = "") -> None:
        self.empty = empty
        self.text = text or "def handler():\n    builder.build()"
        self.asked: list[tuple[str, str]] = []

    def _answer(self) -> NavigationAnswer:
        if self.empty:
            return NavigationAnswer(source=self.source)
        return NavigationAnswer(
            source=self.source,
            fragments=(
                CodeFragment(
                    path="app/api.py",
                    start_line=5,
                    end_line=6,
                    text=self.text,
                    role=FragmentRole.CALLER,
                    title="app.api.handler · function",
                ),
            ),
        )

    async def search_code(self, query: str, *, limit: int = 10) -> NavigationAnswer:
        self.asked.append(("search_code", query))
        return self._answer()

    async def get_definition(self, name: str, *, limit: int = 5) -> NavigationAnswer:
        self.asked.append(("get_definition", name))
        return self._answer()

    async def find_references(
        self,
        name: str,
        *,
        relation: ReferenceRelation = ReferenceRelation.ANY,
        limit: int = 20,
    ) -> NavigationAnswer:
        self.asked.append(("find_references", name))
        return self._answer()

    async def find_callers(self, name: str, *, limit: int = 20) -> NavigationAnswer:
        self.asked.append(("find_callers", name))
        return self._answer()

    async def get_file_context(
        self,
        path: str,
        *,
        start_line: int,
        end_line: int,
        limit: int = 10,
    ) -> NavigationAnswer:
        self.asked.append(("get_file_context", path))
        return self._answer()


class RecordingSink:
    def __init__(self) -> None:
        self.steps: list[InvestigationStep] = []

    async def record(self, step: InvestigationStep) -> None:
        self.steps.append(step)


def build_reviewer(
    client: Any,
    *,
    sink: RecordingSink | None = None,
    max_steps: int = 5,
    fallback_content: str = EMPTY_JSON,
) -> AgenticCodeReviewer:
    return AgenticCodeReviewer(
        client,
        fallback=LlmCodeReviewer(FakeLlmClient(fallback_content)),
        max_steps=max_steps,
        sink=sink,
    )


async def review(
    reviewer: AgenticCodeReviewer,
    navigator: Any = None,
    *,
    cancellation: Any = None,
    diff: RunDiff | None = None,
) -> FileReviewResult:
    file = build_file()
    return await reviewer.review_file(
        file,
        patch_text=file.to_unified_patch(),
        requirements=ModelRequirements(),
        support=ReviewSupport(
            navigator=navigator,
            cancellation=cancellation,
            diff=diff or RunDiff(),
        ),
    )


async def test_tool_call_is_executed_and_answer_comes_back() -> None:
    client = ScriptedLlmClient([answer(calls=(call(),)), answer(FINDINGS_JSON)])
    navigator = FakeNavigator()

    result = await review(build_reviewer(client), navigator)

    assert navigator.asked == [("find_callers", "build")]
    assert len(result.drafts) == 1
    assert result.drafts[0].title == "Проверка дублей убрана"


async def test_tool_result_reaches_the_dialogue_paired_with_its_call() -> None:
    """Провайдер отвергает переписку, где вызов остался без ответа."""
    client = ScriptedLlmClient([answer(calls=(call(),)), answer(FINDINGS_JSON)])

    await review(build_reviewer(client), FakeNavigator())

    dialogue = client.calls[1]
    assistant = next(message for message in dialogue if message.role is LlmRole.ASSISTANT)
    tool_answer = next(message for message in dialogue if message.role is LlmRole.TOOL)
    assert assistant.tool_calls[0].id == "call_1"
    assert tool_answer.tool_call_id == "call_1"
    assert "app.api.handler" in tool_answer.content


async def test_tools_are_offered_while_investigating_and_dropped_at_the_end() -> None:
    """Пока инструменты на столе, модель вправе попросить ещё вызов вместо ответа."""
    client = ScriptedLlmClient(
        [answer(calls=(call(),)), answer(calls=(call(),)), answer(EMPTY_JSON)]
    )

    await review(build_reviewer(client, max_steps=2), FakeNavigator())

    assert client.offered_tools[0] == (
        "describe_repository",
        "search_code",
        "find_symbol",
        "get_definition",
        "find_callers",
        "find_references",
        "get_file_context",
        "get_file_outline",
        "read_file",
        "list_files",
        "project_docs",
    )
    assert client.offered_tools[-1] == ()
    assert client.schemas[-1] is not None


async def test_answer_without_calls_is_taken_as_is() -> None:
    """Просить модель повторить сказанное — лишнее обращение ценой в минуты."""
    client = ScriptedLlmClient([answer(LOCAL_FINDING_JSON)])

    result = await review(build_reviewer(client), FakeNavigator())

    assert len(client.calls) == 1
    assert len(result.drafts) == 1


async def test_truncated_calls_are_refused_instead_of_executed() -> None:
    """Аргументы оборванного вызова выглядят целыми, а обрезаны посередине."""
    client = ScriptedLlmClient(
        [answer(calls=(call(),), truncated=True), answer(FINDINGS_JSON)],
    )
    navigator = FakeNavigator()

    await review(build_reviewer(client), navigator)

    assert navigator.asked == []
    refusal = next(message for message in client.calls[1] if message.role is LlmRole.TOOL)
    assert "оборвался на лимите" in refusal.content


async def test_broken_arguments_come_back_as_an_error_not_an_exception() -> None:
    client = ScriptedLlmClient(
        [answer(calls=(call(arguments='{"name": "bui'),)), answer(EMPTY_JSON)],
    )
    sink = RecordingSink()

    result = await review(build_reviewer(client, sink=sink), FakeNavigator())

    assert result.drafts == []
    failed = [step for step in sink.steps if step.is_error]
    assert failed and "JSON" in failed[0].detail


async def test_unknown_tool_is_answered_with_the_list_of_real_ones() -> None:
    client = ScriptedLlmClient([answer(calls=(call(name="run_tests"),)), answer(EMPTY_JSON)])
    sink = RecordingSink()

    await review(build_reviewer(client, sink=sink), FakeNavigator())

    failed = [step for step in sink.steps if step.is_error]
    assert failed and "find_callers" in failed[0].detail


async def test_investigation_is_recorded_step_by_step() -> None:
    """Агент, чьи шаги не видны, отличается от одного прохода только временем."""
    client = ScriptedLlmClient([answer("Посмотрю вызывающих", calls=(call(),)), answer(EMPTY_JSON)])
    sink = RecordingSink()

    await review(build_reviewer(client, sink=sink), FakeNavigator())

    kinds = [step.kind for step in sink.steps]
    assert StepKind.THOUGHT in kinds
    assert StepKind.TOOL_CALL in kinds
    assert StepKind.TOOL_RESULT in kinds
    assert kinds[-1] is StepKind.ANSWER
    assert sink.steps[0].file_path == "app/service.py"


async def test_without_a_navigator_the_reviewer_falls_back() -> None:
    client = ScriptedLlmClient([answer(FINDINGS_JSON)])
    sink = RecordingSink()

    result = await review(build_reviewer(client, sink=sink, fallback_content=EMPTY_JSON))

    assert client.calls == []
    assert result.drafts == []
    assert sink.steps[0].kind is StepKind.FALLBACK
    assert "инструменты" in sink.steps[0].detail


async def test_context_overflow_falls_back_instead_of_failing() -> None:
    """Файл без ревью неотличим от файла без замечаний."""

    class OverflowingClient(ScriptedLlmClient):
        async def complete(
            self,
            messages: list[LlmMessage],
            *,
            requirements: ModelRequirements,
            json_schema: dict[str, Any] | None = None,
            tools: Sequence[ToolSpec] | None = None,
        ) -> LlmResponse:
            raise LlmContextOverflowError("окно кончилось", model="fake-model")

    sink = RecordingSink()
    reviewer = build_reviewer(OverflowingClient([]), sink=sink, fallback_content=FINDINGS_JSON)

    result = await review(reviewer, FakeNavigator())

    assert len(result.drafts) == 1
    assert sink.steps[-1].kind is StepKind.FALLBACK


async def test_step_limit_forces_the_answer() -> None:
    client = ScriptedLlmClient([answer(calls=(call(),))] * 2 + [answer(FINDINGS_JSON)])

    result = await review(build_reviewer(client, max_steps=2), FakeNavigator())

    assert len(client.calls) == 3
    assert len(result.drafts) == 1


async def test_unparseable_conclusion_falls_back_to_one_pass() -> None:
    """Одноразовый проход по тому же файлу ещё может ответить — падение уже нет."""
    client = ScriptedLlmClient([answer("мне нечего добавить")])
    sink = RecordingSink()

    result = await review(
        build_reviewer(client, sink=sink, fallback_content=FINDINGS_JSON),
        FakeNavigator(),
    )

    assert len(result.drafts) == 1
    assert sink.steps[-1].kind is StepKind.FALLBACK
    assert "не разобрался" in sink.steps[-1].detail


async def test_claim_about_other_code_is_sent_back_once() -> None:
    """«Сломает вызывающих» без единого вызова — догадка, выданная за факт."""
    client = ScriptedLlmClient(
        [answer(FINDINGS_JSON), answer(calls=(call(),)), answer(FINDINGS_JSON)]
    )
    navigator = FakeNavigator()

    result = await review(build_reviewer(client), navigator)

    nudge = client.calls[1][-1].content
    assert "you have not looked at that code" in nudge
    assert navigator.asked == [("find_callers", "build")]
    assert len(result.drafts) == 1


async def test_the_model_is_sent_back_only_once() -> None:
    """Упрямый ответ принимается со второго раза, а не крутит цикл до предела."""
    client = ScriptedLlmClient([answer(FINDINGS_JSON)])

    result = await review(build_reviewer(client, max_steps=4), FakeNavigator())

    assert len(client.calls) == 2
    assert len(result.drafts) == 1


async def test_claim_checked_by_a_tool_passes_without_a_nudge() -> None:
    client = ScriptedLlmClient([answer(calls=(call(),)), answer(FINDINGS_JSON)])

    result = await review(build_reviewer(client), FakeNavigator())

    assert len(client.calls) == 2
    assert len(result.drafts) == 1


async def test_stop_is_heard_between_calls_to_the_model() -> None:
    """Цикл идёт до шести обращений — это десяток минут на локальной модели."""
    client = ScriptedLlmClient([answer(calls=(call(),)), answer(FINDINGS_JSON)])

    async def stop() -> bool:
        return True

    with pytest.raises(ReviewInterruptedError):
        await review(build_reviewer(client), FakeNavigator(), cancellation=stop)

    assert client.calls == []


async def test_shown_code_comes_back_for_the_evidence_check() -> None:
    """Цитата из ответа инструмента — доказательство наравне с патчем (D-008)."""
    client = ScriptedLlmClient([answer(calls=(call(),)), answer(FINDINGS_JSON)])

    result = await review(build_reviewer(client), FakeNavigator())

    assert [fragment.path for fragment in result.shown] == ["app/api.py"]
    assert "builder.build()" in result.shown[0].text


async def test_nothing_is_shown_when_the_tool_found_nothing() -> None:
    client = ScriptedLlmClient([answer(calls=(call(),)), answer(EMPTY_JSON)])

    result = await review(build_reviewer(client), FakeNavigator(empty=True))

    assert result.shown == ()


async def test_usage_of_every_step_is_counted() -> None:
    """Прогон отчитывается о стоимости целиком, а не по последнему обращению."""
    client = ScriptedLlmClient([answer(calls=(call(),)), answer(FINDINGS_JSON)])

    result = await review(build_reviewer(client), FakeNavigator())

    assert result.usage.input_tokens == 200
    assert result.usage.output_tokens == 100


async def test_the_rest_of_the_diff_is_offered_when_the_run_has_other_files() -> None:
    """Ревьюер видит свой файл; правка живёт в нескольких."""
    client = ScriptedLlmClient([answer(FINDINGS_JSON)])
    neighbour = build_file()
    neighbour.path = "app/api.py"

    await review(
        build_reviewer(client),
        FakeNavigator(),
        diff=RunDiff((build_file(), neighbour)),
    )

    assert "get_diff_summary" in client.offered_tools[0]
    assert "get_file_diff" in client.offered_tools[0]


async def test_a_single_file_run_offers_navigation_only() -> None:
    client = ScriptedLlmClient([answer(FINDINGS_JSON)])

    await review(build_reviewer(client), FakeNavigator(), diff=RunDiff((build_file(),)))

    assert "get_diff_summary" not in client.offered_tools[0]


async def test_full_window_forces_the_answer_before_the_step_ceiling() -> None:
    """Рабочий ограничитель — окно, а не счётчик обращений."""
    client = ScriptedLlmClient(
        [answer(calls=(call(),), input_tokens=9000, context_window=10000), answer(FINDINGS_JSON)]
    )
    sink = RecordingSink()

    result = await review(build_reviewer(client, sink=sink, max_steps=10), FakeNavigator())

    assert len(client.calls) == 2
    assert len(result.drafts) == 1
    assert any("заполнил окно" in step.detail for step in sink.steps)


async def test_unknown_window_leaves_the_ceiling_in_charge() -> None:
    client = ScriptedLlmClient(
        [answer(calls=(call(),), input_tokens=9000)] * 3 + [answer(EMPTY_JSON)]
    )
    sink = RecordingSink()

    await review(build_reviewer(client, sink=sink, max_steps=3), FakeNavigator())

    assert len(client.calls) == 4
    assert any("потолок обращений" in step.detail for step in sink.steps)


async def test_repeated_call_is_refused_instead_of_executed() -> None:
    """Второй такой же вызов — место в окне, потраченное на то, что уже есть."""
    client = ScriptedLlmClient(
        [
            answer(calls=(call(arguments='{"name": "build"}'),)),
            answer(calls=(call(arguments='{"name":"build"}'),)),
            answer(EMPTY_JSON),
        ]
    )
    navigator = FakeNavigator()

    await review(build_reviewer(client), navigator)

    assert navigator.asked == [("find_callers", "build")]
    refusal = [message for message in client.calls[2] if message.role is LlmRole.TOOL][-1]
    assert "уже был" in refusal.content


async def test_tool_result_limit_follows_the_model_window() -> None:
    """Окно в 128 000 не режется до размера 16 000."""
    long_text = "\n".join(f"line {number}" for number in range(400))
    scripted = [answer(calls=(call(),), context_window=128000), answer(EMPTY_JSON)]
    client = ScriptedLlmClient(scripted)

    await review(build_reviewer(client), FakeNavigator(text=long_text))

    tool_answer = next(message for message in client.calls[1] if message.role is LlmRole.TOOL)
    assert "ответ обрезан" not in tool_answer.content


async def test_tool_result_is_clipped_when_the_window_is_unknown() -> None:
    long_text = "\n".join(f"line {number}" for number in range(400))
    client = ScriptedLlmClient([answer(calls=(call(),)), answer(EMPTY_JSON)])

    await review(build_reviewer(client), FakeNavigator(text=long_text))

    tool_answer = next(message for message in client.calls[1] if message.role is LlmRole.TOOL)
    assert "ответ обрезан" in tool_answer.content


async def test_conclusion_without_json_is_asked_again_once() -> None:
    """Расследование стоит десятки обращений; один сбой формата их не выбрасывает."""
    client = ScriptedLlmClient(
        [answer(calls=(call(),)), answer("Подумав, я считаю..."), answer(FINDINGS_JSON)]
    )
    sink = RecordingSink()

    result = await review(build_reviewer(client, sink=sink, max_steps=1), FakeNavigator())

    assert len(client.calls) == 3
    assert "no JSON object" in client.calls[2][-1].content
    assert len(result.drafts) == 1
    assert any("Подумав" in step.detail for step in sink.steps if step.kind is StepKind.THOUGHT)


async def test_second_answer_without_json_falls_back() -> None:
    client = ScriptedLlmClient([answer(calls=(call(),)), answer("не могу")])
    sink = RecordingSink()

    result = await review(
        build_reviewer(client, sink=sink, max_steps=1, fallback_content=FINDINGS_JSON),
        FakeNavigator(),
    )

    assert len(client.calls) == 3
    assert len(result.drafts) == 1
    assert sink.steps[-1].kind is StepKind.FALLBACK


async def test_closing_answer_gets_an_output_budget_from_the_window() -> None:
    """Рассуждающая модель думает в том же бюджете, что и пишет."""
    client = ScriptedLlmClient(
        [answer(calls=(call(),), context_window=128000), answer(FINDINGS_JSON)]
    )

    await review(build_reviewer(client, max_steps=1), FakeNavigator())

    assert client.requirements[-1].max_output_tokens == 16000
    assert client.requirements[0].max_output_tokens == 4096


async def test_unknown_window_keeps_the_output_budget() -> None:
    client = ScriptedLlmClient([answer(calls=(call(),)), answer(FINDINGS_JSON)])

    await review(build_reviewer(client, max_steps=1), FakeNavigator())

    assert client.requirements[-1].max_output_tokens == 4096


async def test_truncated_closing_answer_is_asked_to_be_shorter() -> None:
    client = ScriptedLlmClient(
        [answer(calls=(call(),)), answer("", truncated=True), answer(FINDINGS_JSON)]
    )

    result = await review(build_reviewer(client, max_steps=1), FakeNavigator())

    assert "at most five findings" in client.calls[2][-1].content
    assert len(result.drafts) == 1
