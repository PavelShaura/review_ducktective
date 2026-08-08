import time

from ducktective.core.exceptions import (
    LlmContextOverflowError,
    LlmOutputError,
)
from ducktective.core.llm.ports import (
    LlmClient,
)
from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmResponse,
    LlmRole,
    LlmUsage,
    ModelRequirements,
    ToolCall,
)
from ducktective.core.retrieval.context import (
    DiffContext,
)
from ducktective.core.retrieval.navigation import (
    CodeFragment,
    CodeNavigator,
)
from ducktective.core.review.entities import (
    ReviewFile,
)
from ducktective.core.review.investigation import (
    MAX_STEP_DETAIL_CHARS,
    InvestigationSink,
    InvestigationStep,
    NullInvestigationSink,
    StepKind,
)
from ducktective.core.review.ports import (
    CodeReviewer,
    FileReviewResult,
)
from ducktective.core.review.reviewers import (
    ReviewMode,
    reviewer_name,
)
from ducktective.llm.code_reviewer import (
    build_user_message,
    parse_payload,
    system_prompt,
    to_draft,
)
from ducktective.llm.schemas import (
    ReviewPayload,
)
from ducktective.llm.tools import (
    NavigationToolbox,
)


DEFAULT_MAX_STEPS = 5
"""Сколько раз агент может обратиться к модели с инструментами на столе.

Ограничение не про деньги и не про скорость: при восьмидесяти токенах
в секунду лишнее обращение стоит секунд. Ограничено окно — каждый результат
инструмента остаётся в диалоге до конца, и на шестом вызове разбирать
будет уже негде.
"""

TRUNCATED_CALLS_MESSAGE = (
    "Your previous message hit the output token limit, so the arguments of your tool "
    "calls may be incomplete. None of them were executed. Re-issue the call you need, "
    "one at a time, or answer with your findings."
)

FINAL_INSTRUCTION = (
    "Stop investigating and answer now. Return the JSON object with your findings and nothing else."
)


class AgenticCodeReviewer:
    """Ревьюер, который сам решает, что ему посмотреть.

    Отличие от одноразового прохода одно: окружение не только собирается
    заранее, но и дозапрашивается по ходу. Модель получает патч, то, что уже
    собрано, и перечень инструментов; цикл идёт, пока она просит вызовы,
    и кончается структурированным ответом.

    Три вещи цикл обязан ограничивать — число обращений, размер каждого
    результата и общий расход токенов. Все три упираются в одно: окно модели,
    которое цикл копит быстрее одноразового прохода.

    Откат к проходу без инструментов случается в трёх случаях: инструментов
    нет вовсе, диалог не поместился в окно, итог расследования не разобрался.
    Во всех трёх падение было бы хуже: файл без ревью неотличим от файла
    без замечаний, а одноразовый проход по тому же файлу ещё может ответить.
    """

    def __init__(
        self,
        llm_client: LlmClient,
        *,
        fallback: CodeReviewer,
        max_steps: int = DEFAULT_MAX_STEPS,
        token_budget: int = 0,
        sink: InvestigationSink | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._fallback = fallback
        self._max_steps = max_steps
        self._token_budget = token_budget
        self._sink = sink or NullInvestigationSink()
        self.name = reviewer_name(ReviewMode.AGENTIC)

    async def review_file(
        self,
        file: ReviewFile,
        *,
        patch_text: str,
        requirements: ModelRequirements,
        context: DiffContext | None = None,
        navigator: CodeNavigator | None = None,
    ) -> FileReviewResult:
        if navigator is None:
            return await self._fall_back(
                file,
                patch_text=patch_text,
                requirements=requirements,
                context=context,
                reason="инструменты навигации недоступны",
            )

        try:
            return await self._investigate(
                file,
                patch_text=patch_text,
                requirements=requirements,
                context=context,
                navigator=navigator,
            )
        except LlmContextOverflowError as error:
            return await self._fall_back(
                file,
                patch_text=patch_text,
                requirements=requirements,
                context=context,
                reason=f"диалог не поместился в окно модели: {error}",
            )
        except LlmOutputError as error:
            return await self._fall_back(
                file,
                patch_text=patch_text,
                requirements=requirements,
                context=context,
                reason=f"итог расследования не разобрался: {error}",
            )

    async def _investigate(
        self,
        file: ReviewFile,
        *,
        patch_text: str,
        requirements: ModelRequirements,
        context: DiffContext | None,
        navigator: CodeNavigator,
    ) -> FileReviewResult:
        toolbox = NavigationToolbox(navigator)
        tool_requirements = _with_tool_calling(requirements)
        messages = [
            LlmMessage(role=LlmRole.SYSTEM, content=system_prompt(with_tools=True)),
            LlmMessage(role=LlmRole.USER, content=build_user_message(file, patch_text, context)),
        ]

        usage = LlmUsage()
        shown: list[CodeFragment] = []
        step = 0
        model = ""

        for _ in range(self._max_steps):
            response = await self._llm_client.complete(
                messages,
                requirements=tool_requirements,
                tools=toolbox.specs,
            )
            usage = _add(usage, response.usage)
            model = response.model
            step += 1

            if response.has_tool_calls and response.is_truncated:
                messages.extend(
                    [
                        _assistant(response),
                        *_refused(response.tool_calls),
                        LlmMessage(role=LlmRole.USER, content=TRUNCATED_CALLS_MESSAGE),
                    ]
                )
                await self._record(file, step, StepKind.THOUGHT, TRUNCATED_CALLS_MESSAGE)
                continue

            if not response.has_tool_calls:
                answered = _answer_of(response)
                if answered is not None:
                    return await self._finish(
                        file,
                        answered,
                        usage,
                        response.model or model,
                        step,
                        shown,
                    )
                break

            await self._record(file, step, StepKind.THOUGHT, response.content)
            messages.append(_assistant(response))
            for call in response.tool_calls:
                step += 1
                message, fragments = await self._run_tool(toolbox, call, file, step)
                messages.append(message)
                shown.extend(fragments)

            if self._out_of_budget(usage):
                break

        return await self._conclude(
            file,
            messages=messages,
            requirements=requirements,
            usage=usage,
            model=model,
            step=step,
            shown=shown,
        )

    async def _run_tool(
        self,
        toolbox: NavigationToolbox,
        call: ToolCall,
        file: ReviewFile,
        step: int,
    ) -> tuple[LlmMessage, tuple[CodeFragment, ...]]:
        """Исполняет вызов и возвращает показанное вместе с ответом модели.

        Показанное копится не для отчёта: цитата из ответа инструмента —
        доказательство наравне с патчем, и проверить её потом можно только
        по тому, что инструмент действительно вернул (D-008).
        """
        await self._record(
            file,
            step,
            StepKind.TOOL_CALL,
            "",
            tool_name=call.name,
            arguments=call.arguments,
        )

        started_at = time.monotonic()
        result = await toolbox.execute(call)
        duration_ms = int((time.monotonic() - started_at) * 1000)

        await self._record(
            file,
            step,
            StepKind.TOOL_RESULT,
            result.text,
            tool_name=call.name,
            duration_ms=duration_ms,
            is_error=result.is_error,
        )
        return (
            LlmMessage(role=LlmRole.TOOL, content=result.text, tool_call_id=call.id),
            result.fragments,
        )

    async def _conclude(
        self,
        file: ReviewFile,
        *,
        messages: list[LlmMessage],
        requirements: ModelRequirements,
        usage: LlmUsage,
        model: str,
        step: int,
        shown: list[CodeFragment],
    ) -> FileReviewResult:
        """Вынуждает структурированный ответ, когда цикл кончился.

        Последнее обращение идёт без инструментов и со схемой: пока инструменты
        на столе, модель вправе попросить ещё вызов, и цикл, у которого шаги
        кончились, получил бы вместо находок очередную просьбу.
        """
        response = await self._llm_client.complete(
            [*messages, LlmMessage(role=LlmRole.USER, content=FINAL_INSTRUCTION)],
            requirements=requirements,
            json_schema=ReviewPayload.model_json_schema(),
        )
        payload = parse_payload(response.content, model=response.model)

        return await self._finish(
            file,
            payload,
            _add(usage, response.usage),
            response.model or model,
            step + 1,
            shown,
        )

    async def _finish(
        self,
        file: ReviewFile,
        payload: ReviewPayload,
        usage: LlmUsage,
        model: str,
        step: int,
        shown: list[CodeFragment],
    ) -> FileReviewResult:
        await self._record(
            file,
            step,
            StepKind.ANSWER,
            f"Расследование закончено, находок: {len(payload.findings)}",
        )
        return FileReviewResult(
            drafts=[to_draft(finding, file.path) for finding in payload.findings],
            usage=usage,
            model=model,
            shown=tuple(shown),
        )

    async def _fall_back(
        self,
        file: ReviewFile,
        *,
        patch_text: str,
        requirements: ModelRequirements,
        context: DiffContext | None,
        reason: str,
    ) -> FileReviewResult:
        """Уходит на проход без инструментов, назвав причину.

        Причина попадает в трассу, а не только в лог: расследование, которого
        не было, и расследование, где агент ничего не нашёл, — разные события,
        и в ленте они обязаны выглядеть по-разному.
        """
        await self._record(file, 1, StepKind.FALLBACK, reason)
        return await self._fallback.review_file(
            file,
            patch_text=patch_text,
            requirements=requirements,
            context=context,
        )

    def _out_of_budget(self, usage: LlmUsage) -> bool:
        if self._token_budget <= 0:
            return False
        return usage.input_tokens + usage.output_tokens >= self._token_budget

    async def _record(
        self,
        file: ReviewFile,
        step: int,
        kind: StepKind,
        detail: str,
        *,
        tool_name: str | None = None,
        arguments: str | None = None,
        duration_ms: int = 0,
        is_error: bool = False,
    ) -> None:
        if kind is StepKind.THOUGHT and not detail.strip():
            return

        await self._sink.record(
            InvestigationStep(
                file_path=file.path,
                number=step,
                kind=kind,
                tool_name=tool_name,
                arguments=arguments,
                detail=detail[:MAX_STEP_DETAIL_CHARS],
                duration_ms=duration_ms,
                is_error=is_error,
            )
        )


def _with_tool_calling(requirements: ModelRequirements) -> ModelRequirements:
    """Требование к модели на время цикла.

    Роутер выбирает по нему провайдера: модель без вызова инструментов
    диалога не выдержит, и узнать об этом нужно до первого обращения.
    """
    return ModelRequirements(
        needs_deep_reasoning=requirements.needs_deep_reasoning,
        needs_tool_calling=True,
        cloud_allowed=requirements.cloud_allowed,
        max_output_tokens=requirements.max_output_tokens,
        temperature=requirements.temperature,
    )


def _answer_of(response: LlmResponse) -> ReviewPayload | None:
    """Разбирает ответ, если модель уже ответила находками.

    Просить её повторить то, что она только что сказала, — это лишнее
    обращение к модели ценой в минуты на локальном железе. Неразобранный
    ответ не беда: за ним идёт вынужденный структурированный вопрос.
    """
    if not response.content.strip():
        return None
    try:
        return parse_payload(response.content, model=response.model)
    except LlmOutputError:
        return None


def _assistant(response: LlmResponse) -> LlmMessage:
    return LlmMessage(
        role=LlmRole.ASSISTANT,
        content=response.content,
        tool_calls=response.tool_calls,
    )


def _refused(calls: tuple[ToolCall, ...]) -> list[LlmMessage]:
    """Отказ исполнять вызовы из оборванного на лимите ответа.

    Аргументы такого вызова разбираются и выглядят целыми, а на деле обрезаны
    посередине: `get_file_context` с потерянной половиной диапазона строк
    выполнится и вернёт не то, о чём просили. Ответить на каждый вызов
    обязательно — провайдер отвергает переписку, где вызов остался без ответа.
    """
    return [
        LlmMessage(
            role=LlmRole.TOOL,
            content="Вызов не выполнен: ответ модели оборвался на лимите токенов.",
            tool_call_id=call.id,
        )
        for call in calls
    ]


def _add(total: LlmUsage, addition: LlmUsage) -> LlmUsage:
    return LlmUsage(
        input_tokens=total.input_tokens + addition.input_tokens,
        output_tokens=total.output_tokens + addition.output_tokens,
        cost_usd=total.cost_usd + addition.cost_usd,
    )
