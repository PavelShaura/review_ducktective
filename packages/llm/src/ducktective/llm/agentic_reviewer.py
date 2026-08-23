import time

from ducktective.core.exceptions import (
    LlmContextOverflowError,
    LlmOutputError,
    ReviewInterruptedError,
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
    ReviewSupport,
)
from ducktective.core.review.reviewers import (
    ReviewMode,
    reviewer_name,
)
from ducktective.core.review.verification import (
    mentions_external_code,
)
from ducktective.llm.code_reviewer import (
    build_user_message,
    describe_findings,
    parse_payload,
    system_prompt,
    to_draft,
)
from ducktective.llm.review_tools import (
    ReviewToolbox,
)
from ducktective.llm.schemas import (
    ReviewPayload,
)
from ducktective.llm.tools import (
    NavigationToolbox,
    Toolbox,
)


DEFAULT_MAX_STEPS = 5
"""Сколько раз агент может обратиться к модели с инструментами на столе.

Ограничение не про деньги и не про скорость: при восьмидесяти токенах
в секунду лишнее обращение стоит секунд. Ограничено окно — каждый результат
инструмента остаётся в диалоге до конца, и на шестом вызове разбирать
будет уже негде.
"""

AGENTIC_MIN_CONTEXT_TOKENS = 16384
"""Окно, ниже которого цикл не имеет смысла.

Измерено, а не выбрано: при 8192 системный промпт, собранное окружение
и зарезервированный ответ оставляли на дифф около тысячи токенов — файлы
крупнее падали с `exceed_context_size_error` ещё в одноразовом проходе.
Диалог с инструментами копит поверх этого каждый показанный фрагмент,
поэтому меньше шестнадцати тысяч он упирается в потолок раньше, чем успевает
что-нибудь выяснить.

Требование заявляется роутеру: узел не выбирает модель сам, но обязан сказать,
чего ему не хватит.
"""

TRUNCATED_CALLS_MESSAGE = (
    "Your previous message hit the output token limit, so the arguments of your tool "
    "calls may be incomplete. None of them were executed. Re-issue the call you need, "
    "one at a time, or answer with your findings."
)

FINAL_INSTRUCTION = (
    "Stop investigating and answer now. Return the JSON object with your findings and nothing else."
)

UNPROVEN_CLAIM_MESSAGE = (
    "Your answer claims something about code outside the diff — callers, contracts or "
    "project conventions — but you have not looked at that code. Call the tool that checks "
    "it and answer again. If you cannot check it, drop the claim or lower its severity."
)

UNPROVEN_CLAIM_NOTE = "Ответ говорит о чужом коде — прошу сперва посмотреть его инструментом"
"""Как переспрос выглядит в ленте.

Модели уходит английский текст, человеку показывается русская строка и вид
«этап»: это реплика конвейера, а не мысль модели, и выдавать её за мысль
значит приписывать модели наши слова.
"""


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
        support: ReviewSupport | None = None,
    ) -> FileReviewResult:
        run = support or ReviewSupport()
        listener = run.sink or self._sink
        navigator = run.navigator

        if navigator is None:
            return await self._fall_back(
                file,
                patch_text=patch_text,
                requirements=requirements,
                context=context,
                listener=listener,
                reason="инструменты навигации недоступны",
            )

        try:
            return await self._investigate(
                file,
                patch_text=patch_text,
                requirements=requirements,
                context=context,
                navigator=navigator,
                listener=listener,
                support=run,
            )
        except LlmContextOverflowError as error:
            return await self._fall_back(
                file,
                patch_text=patch_text,
                requirements=requirements,
                context=context,
                listener=listener,
                reason=f"диалог не поместился в окно модели: {error}",
            )
        except LlmOutputError as error:
            return await self._fall_back(
                file,
                patch_text=patch_text,
                requirements=requirements,
                context=context,
                listener=listener,
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
        listener: InvestigationSink,
        support: ReviewSupport,
    ) -> FileReviewResult:
        toolbox = ReviewToolbox(
            NavigationToolbox(navigator),
            support.diff,
            path=file.path,
            history=support.history,
            repository_id=support.repository_id,
        )
        tool_requirements = _with_tool_calling(requirements)
        messages = [
            LlmMessage(role=LlmRole.SYSTEM, content=system_prompt(with_tools=True)),
            LlmMessage(role=LlmRole.USER, content=build_user_message(file, patch_text, context)),
        ]

        usage = LlmUsage()
        shown: list[CodeFragment] = []
        step = 0
        model = ""
        nudged = False

        for attempt in range(1, self._max_steps + 1):
            if await support.stop_requested():
                raise ReviewInterruptedError("Расследование прекращено")

            await self._record(
                listener,
                file,
                step,
                StepKind.STAGE,
                f"Спрашиваю модель, обращение {attempt} из {self._max_steps}",
            )
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
                await self._record(
                    listener,
                    file,
                    step,
                    StepKind.STAGE,
                    "Ответ модели оборвался на лимите — прошу повторить вызов",
                )
                continue

            if not response.has_tool_calls:
                answered = _answer_of(response)
                if answered is None:
                    break

                if not shown and not nudged and _claims_unchecked_code(answered):
                    nudged = True
                    messages.extend(
                        [
                            _assistant(response),
                            LlmMessage(role=LlmRole.USER, content=UNPROVEN_CLAIM_MESSAGE),
                        ]
                    )
                    await self._record(listener, file, step, StepKind.STAGE, UNPROVEN_CLAIM_NOTE)
                    continue

                return await self._finish(
                    file,
                    answered,
                    usage,
                    response.model or model,
                    step,
                    shown,
                    listener,
                )

            await self._record(listener, file, step, StepKind.THOUGHT, response.content)
            messages.append(_assistant(response))
            for call in response.tool_calls:
                step += 1
                message, fragments = await self._run_tool(toolbox, call, file, step, listener)
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
            listener=listener,
        )

    async def _run_tool(
        self,
        toolbox: Toolbox,
        call: ToolCall,
        file: ReviewFile,
        step: int,
        listener: InvestigationSink,
    ) -> tuple[LlmMessage, tuple[CodeFragment, ...]]:
        """Исполняет вызов и возвращает показанное вместе с ответом модели.

        Показанное копится не для отчёта: цитата из ответа инструмента —
        доказательство наравне с патчем, и проверить её потом можно только
        по тому, что инструмент действительно вернул (D-008).
        """
        await self._record(
            listener,
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
            listener,
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
        listener: InvestigationSink,
    ) -> FileReviewResult:
        """Вынуждает структурированный ответ, когда цикл кончился.

        Последнее обращение идёт без инструментов и со схемой: пока инструменты
        на столе, модель вправе попросить ещё вызов, и цикл, у которого шаги
        кончились, получил бы вместо находок очередную просьбу.
        """
        await self._record(
            listener,
            file,
            step,
            StepKind.STAGE,
            "Спрашиваю модель в последний раз: прошу назвать находки",
        )
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
            listener,
        )

    async def _finish(
        self,
        file: ReviewFile,
        payload: ReviewPayload,
        usage: LlmUsage,
        model: str,
        step: int,
        shown: list[CodeFragment],
        listener: InvestigationSink,
    ) -> FileReviewResult:
        await self._record(
            listener,
            file,
            step,
            StepKind.ANSWER,
            describe_findings(payload),
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
        listener: InvestigationSink,
        reason: str,
    ) -> FileReviewResult:
        """Уходит на проход без инструментов, назвав причину.

        Причина попадает в трассу, а не только в лог: расследование, которого
        не было, и расследование, где агент ничего не нашёл, — разные события,
        и в ленте они обязаны выглядеть по-разному.
        """
        await self._record(listener, file, 1, StepKind.FALLBACK, reason)
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
        listener: InvestigationSink,
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

        await listener.record(
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
    Окно заявляется тем же способом и по той же причине — цикл копит диалог,
    и модели, которой хватало на один проход, ему может не хватить.
    """
    return ModelRequirements(
        needs_deep_reasoning=requirements.needs_deep_reasoning,
        needs_tool_calling=True,
        min_context_tokens=max(requirements.min_context_tokens, AGENTIC_MIN_CONTEXT_TOKENS),
        allowed_trust=requirements.allowed_trust,
        preferred_model=requirements.preferred_model,
        max_output_tokens=requirements.max_output_tokens,
        temperature=requirements.temperature,
    )


def _claims_unchecked_code(payload: ReviewPayload) -> bool:
    """Говорит ли ответ о коде, которого ревьюер так и не посмотрел.

    Переспрашивается один раз и только пока ни один инструмент не звали:
    цена — одно обращение к модели, а без него находка «сломает всех
    вызывающих» уйдёт в отбраковку целиком, и работа над ней потрачена зря.
    """
    return any(mentions_external_code(finding.title, finding.body) for finding in payload.findings)


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
