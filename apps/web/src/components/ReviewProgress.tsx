import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/api/client";
import type { DegradationKind, NodeDegradation, ReviewRun, ReviewStage } from "@/api/types";

const AVERAGE_SECONDS_PER_FILE = 25;

const REVIEWER_NAME_PREFIX = "reviewer:";

const STAGE_LABELS: Record<ReviewStage, string> = {
  build_context: "окружение",
  plan_review: "план",
  review: "ревью",
  aggregate: "слияние",
  verify: "проверка",
};

const KIND_LABELS: Record<DegradationKind, string> = {
  context_overflow: "не поместился в окно",
  output_exhausted: "ответ оборван",
  invalid_output: "ответ не разобран",
  timeout: "не ответила",
  rate_limited: "частота запросов",
  provider_unavailable: "модель недоступна",
  context_unavailable: "окружение не собралось",
  unknown: "сбой",
};

/**
 * Причины разделены переносом строки, но в делах, заведённых раньше, они
 * склеены точкой с запятой. Она разделяет только там, где дальше начинается
 * путь: внутри текста ошибки точка с запятой ничего не разрывает.
 */
const REASON_SEPARATOR = /\n|;\s+(?=\S+:\s)/;

/**
 * Сбои модели, у которых есть разбираемая структура. Порядок важен: строка
 * проверяется до первого совпадения. Всё, что не совпало, показывается текстом.
 */
const FAILURE_PATTERNS: {
  pattern: RegExp;
  reason: string;
  read: (match: RegExpExecArray) => { model: string; prompt: string | null; limit: string };
}[] = [
  {
    pattern: /модели (\S+): (\d+) токенов при окне (\d+)/,
    reason: "не поместился в окно",
    read: (match) => ({ model: match[1]!, prompt: match[2]!, limit: `окно ${match[3]!}` }),
  },
  {
    pattern: /Модель (\S+) исчерпала лимит ответа в (\d+) токенов/,
    reason: "ответ оборван",
    read: (match) => ({ model: match[1]!, prompt: null, limit: `ответ ${match[2]!}` }),
  },
  {
    /* Формулировка до 2026-08-02: дела, заведённые раньше, лежат в базе с ней. */
    pattern: /Модель (\S+) оборвала ответ на лимите (\d+) токенов/,
    reason: "ответ оборван",
    read: (match) => ({ model: match[1]!, prompt: null, limit: `ответ ${match[2]!}` }),
  },
  {
    pattern: /Модель (\S+) не ответила за (\d+) с/,
    reason: "не ответила",
    read: (match) => ({ model: match[1]!, prompt: null, limit: `таймаут ${match[2]!} с` }),
  },
  {
    pattern: /Модель (\S+) ограничивает частоту/,
    reason: "частота запросов",
    read: (match) => ({ model: match[1]!, prompt: null, limit: "—" }),
  },
];

/** Что делать с каждым видом сбоя. Совет привязан к виду, а не к формулировке. */
const KIND_ADVICE: Partial<Record<DegradationKind, string>> = {
  context_overflow:
    "Подсказка не влезла в контекстное окно модели. Поднимите окно (n_ctx) до 16384 — " +
    "меньше для ревью не хватает — или уменьшите CONTEXT_TOKEN_BUDGET в .env, пожертвовав " +
    "окружением из индекса.",
  output_exhausted:
    "Модель исписала весь отведённый ответ и не закончила. Место под ответ резервируется " +
    "в окне: системный промпт (~1300 токенов) + CONTEXT_TOKEN_BUDGET + LLM_MAX_OUTPUT_TOKENS " +
    "вычитаются из окна, остаток — всё, что осталось на дифф. Поднимите окно модели; " +
    "если она рассуждает вслух, снижать LLM_MAX_OUTPUT_TOKENS бесполезно — размышления " +
    "занимают большую часть ответа.",
  timeout:
    "Модель не уложилась в отведённое время. Поднимите LLM_TIMEOUT_SECONDS в .env либо " +
    "возьмите модель полегче: при 19 токенах в секунду один файл занимает две-три минуты.",
  rate_limited:
    "Провайдер ограничил частоту обращений. Подождите и отправьте дело на расследование заново.",
  context_unavailable:
    "Окружение из индекса собрать не удалось, и эти файлы прочитаны по одному диффу — " +
    "качество на них ниже обычного. Проверьте состояние индекса репозитория и соберите " +
    "его заново.",
};

/**
 * Тот же совет для дел, заведённых до появления отметок по узлам: у них вид
 * сбоя приходится узнавать по формулировке, а ключ здесь — подпись причины.
 */
const FAILURE_ADVICE: Record<string, string | undefined> = {
  "не поместился в окно": KIND_ADVICE.context_overflow,
  "ответ оборван": KIND_ADVICE.output_exhausted,
  "не ответила": KIND_ADVICE.timeout,
  "частота запросов": KIND_ADVICE.rate_limited,
};

interface Props {
  run: ReviewRun;
}

/**
 * Чем занят индексатор, если прогон ждёт индекс на своей ревизии.
 *
 * Спрашивается только пока прогон в очереди: идущий прогон индекс уже
 * получил или обошёлся без него. Сборка другой ревизии сюда не попадает —
 * прогон её не ждёт.
 */
function useIndexingForRun(run: ReviewRun): string | null {
  const index = useQuery({
    queryKey: ["index-state", run.repository_id],
    queryFn: () => api.getIndexState(run.repository_id),
    enabled: run.status === "queued",
    refetchInterval: run.status === "queued" ? 3000 : false,
  });
  const state = index.data;
  if (run.status !== "queued" || !state || state.commit_sha !== run.head_sha) {
    return null;
  }
  if (state.status === "pending") {
    return "задача ждёт воркера индексации";
  }
  if (state.status === "running") {
    return state.stage_title ?? "идёт сборка";
  }
  return null;
}

/**
 * Пока прогон не завершён, находок в базе нет вообще: они записываются одной
 * транзакцией в конце. Показывать «замечаний нет» до этого момента — врать.
 */
export function ReviewProgress({ run }: Props) {
  const current = useElapsedSeconds(run.started_at);
  const elapsed = Math.round(run.duration_ms / 1000) + current;
  const expected = run.files.length * AVERAGE_SECONDS_PER_FILE;
  const indexing = useIndexingForRun(run);

  return (
    <section className="border border-brass/40 bg-brass/5 px-5 py-4">
      <div className="flex items-baseline gap-3">
        <span aria-hidden className="animate-pulse text-brass">
          ●
        </span>
        <h2 className="font-display text-2xl font-semibold text-paper">
          {indexing ? "Собирается индекс на ревизии дела" : "Расследование идёт"}
        </h2>
      </div>

      <p className="mt-2 text-[16px] text-paper-dim">
        {indexing
          ? `Индекс собран на другой ревизии, а ревью с чужим графом идёт хуже, чем без него. Сейчас: ${indexing}. Ревью начнётся сразу после.`
          : `Модель читает ${run.files.length} файл(ов) по очереди. Замечания появятся сразу все, когда прогон закончится.`}
      </p>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <dl className="flex flex-wrap gap-x-8 gap-y-1">
          <Fact label="идёт" value={formatDuration(elapsed)} />
          <Fact label="ожидаемо" value={`около ${formatDuration(expected)}`} />
        </dl>
        <StopButton runId={run.id} />
      </div>
    </section>
  );
}

function StopButton({ runId }: { runId: string }) {
  const queryClient = useQueryClient();
  const stop = useMutation({
    mutationFn: () => api.cancelRun(runId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["run", runId] }),
  });

  return (
    <button
      type="button"
      onClick={() => stop.mutate()}
      disabled={stop.isPending}
      className="case-label border border-paper-dim/40 px-3 py-1 text-paper-dim transition hover:border-critical/60 hover:text-critical disabled:opacity-50"
    >
      {stop.isPending ? "прекращаю…" : "прекратить"}
    </button>
  );
}

export function ReviewCancelled({ run }: Props) {
  return (
    <section className="border border-paper-dim/30 bg-paper/5 px-5 py-4">
      <h2 className="font-display text-2xl font-semibold text-paper">Расследование прекращено</h2>
      <p className="mt-2 text-[16px] text-paper-dim">
        Замечания не сохранились: они пишутся все сразу в конце прогона. Дифф разобран
        и остался на месте. Продолжение дочитает файлы, до которых прогон не дошёл;
        заново — прочитает все.
      </p>
      <RestartButton runId={run.id} />
    </section>
  );
}

/**
 * Две кнопки рядом: продолжить дороже не бывает, а заново стоит целого прогона.
 * Продолжение стоит первым, потому что после прекращения хотят обычно его —
 * при локальной модели разница измеряется часами.
 */
function RestartButton({ runId }: { runId: string }) {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["run", runId] });
  const resume = useMutation({ mutationFn: () => api.resumeRun(runId), onSuccess: invalidate });
  const restart = useMutation({ mutationFn: () => api.restartRun(runId), onSuccess: invalidate });
  const busy = resume.isPending || restart.isPending;

  return (
    <div className="mt-4 flex flex-wrap items-center gap-3">
      <button
        type="button"
        onClick={() => resume.mutate()}
        disabled={busy}
        className="case-label border border-brass/50 px-4 py-1.5 text-brass transition hover:bg-brass/10 disabled:opacity-50"
      >
        {resume.isPending ? "продолжаю…" : "продолжить"}
      </button>
      <button
        type="button"
        onClick={() => restart.mutate()}
        disabled={busy}
        className="case-label border border-paper-dim/40 px-4 py-1.5 text-paper-dim transition hover:border-brass/60 hover:text-brass disabled:opacity-50"
      >
        {restart.isPending ? "поднимаю дело…" : "расследовать заново"}
      </button>
      {restart.isError || resume.isError ? (
        <p className="case-label w-full text-critical">не вышло — проверьте, что сервис на месте</p>
      ) : null}
    </div>
  );
}

/**
 * Прогон дошёл до конца, но часть файлов осталась непроверенной. Без такой
 * отметки они выглядят как файлы без замечаний, и пустой результат читается
 * как «всё чисто».
 */
export function ReviewDegraded({ run }: Props) {
  if (!run.failure_reason && run.degradations.length === 0) {
    return null;
  }

  const filesWereLost =
    Boolean(run.failure_reason) || run.degradations.some((mark) => mark.stage === "review");

  return (
    <section className="border border-brass/50 bg-brass/10 px-5 py-4">
      <h2 className="font-display text-2xl font-semibold text-paper">
        {filesWereLost ? "Расследование прошло не полностью" : "Расследование прошло без окружения"}
      </h2>
      <Failures run={run} />
    </section>
  );
}

export function ReviewFailure({ run }: Props) {
  return (
    <section className="border-2 border-critical/70 bg-critical/10 px-5 py-4">
      <span className="stamp inline-block text-[12px] text-critical">провал</span>
      <h2 className="mt-2 font-display text-3xl font-semibold text-critical">
        Расследование не удалось
      </h2>
      {run.failure_reason || run.degradations.length > 0 ? (
        <Failures run={run} />
      ) : (
        <p className="mt-2 text-[16px] text-paper-dim">
          Причина не сохранилась. Загляните в журнал воркера — там будет подробность.
        </p>
      )}
      <RestartButton runId={run.id} />
    </section>
  );
}

/**
 * Отметки узлов, если они есть, и разбор текста, если их нет.
 *
 * Дела, заведённые до появления `review_run.config`, знают о сбое одну фразу
 * на весь прогон — их по-прежнему читает разбор текста. Новые приходят
 * разложенными, и гадать по формулировке уже незачем.
 */
function Failures({ run }: Props) {
  if (run.degradations.length === 0) {
    return run.failure_reason ? <Reasons text={run.failure_reason} /> : null;
  }

  return (
    <div className="mt-3 space-y-3">
      {summaryOf(run.failure_reason).map((note, index) => (
        <p key={`note-${index}`} className="text-[15px] leading-relaxed text-paper-dim">
          {note}
        </p>
      ))}
      <DegradationTable marks={run.degradations} />
      <KindAdvice marks={run.degradations} />
    </div>
  );
}

/**
 * Общая фраза о прогоне без перечня сбоев: перечень уже стоит таблицей.
 * Строку с путём в начале узнаём так же, как её узнаёт разбор старых дел.
 */
function summaryOf(failureReason: string | null): string[] {
  if (!failureReason) {
    return [];
  }
  return failureReason
    .split(REASON_SEPARATOR)
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && parseReason(line).path === null);
}

function DegradationTable({ marks }: { marks: NodeDegradation[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="rule border-b">
            <th className="case-label py-1.5 pr-4 font-normal">файл</th>
            <th className="case-label py-1.5 pr-4 font-normal">кто</th>
            <th className="case-label py-1.5 pr-4 font-normal">причина</th>
            <th className="case-label py-1.5 font-normal">модель</th>
          </tr>
        </thead>
        <tbody>
          {marks.map((mark, index) => (
            <tr key={`${index}-${mark.file_path}`} className="align-top">
              <td className="py-2 pr-4">
                <span className="file-chip">{mark.file_path}</span>
              </td>
              <td className="py-2 pr-4 text-[14px] text-paper-dim">{actorOf(mark)}</td>
              <td className="py-2 pr-4">
                <span className="text-[14px] text-paper">{KIND_LABELS[mark.kind]}</span>
                <span className="mt-0.5 block text-[13px] leading-snug text-paper-dim/80">
                  {mark.detail}
                </span>
              </td>
              <td className="py-2 font-mono text-[13px] text-paper-dim">{mark.model ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function KindAdvice({ marks }: { marks: NodeDegradation[] }) {
  const advice = [...new Set(marks.map((mark) => KIND_ADVICE[mark.kind]))].filter(
    (text): text is string => text !== undefined,
  );

  if (advice.length === 0) {
    return null;
  }

  return (
    <div className="rule border-t pt-3">
      <p className="case-label">что с этим делать</p>
      <ul className="mt-1.5 space-y-1.5">
        {advice.map((text) => (
          <li key={text} className="text-[14px] leading-relaxed text-paper-dim">
            {text}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Ревьюер важнее этапа: на этапе ревью он и есть тот, кто упал, а имя этапа
 * там ничего не добавляет. Остальные этапы называются своим именем.
 */
function actorOf(mark: NodeDegradation): string {
  if (mark.reviewer) {
    return mark.reviewer.replace(REVIEWER_NAME_PREFIX, "");
  }
  return STAGE_LABELS[mark.stage];
}

/**
 * Причина хранится текстом: структуры в базе нет, разбор идёт здесь. Строки
 * знакомого вида раскладываются по колонкам, всё прочее показывается как есть,
 * чтобы незнакомая ошибка не пропала из виду.
 */
function Reasons({ text }: { text: string }) {
  const lines = text
    .split(REASON_SEPARATOR)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

  const rows = lines.map(parseReason);
  const failures = rows.filter((row) => row.path !== null);
  const notes = rows.filter((row) => row.path === null);

  return (
    <div className="mt-3 space-y-3">
      {notes.map((note, index) => (
        <p key={`note-${index}`} className="text-[15px] leading-relaxed text-paper-dim">
          {note.detail}
        </p>
      ))}

      {failures.length > 0 ? <ReasonTable rows={failures} /> : null}
      <Advice rows={failures} />
    </div>
  );
}

/**
 * Что делать с этими сбоями. Причина названа кодом настройки, а не намёком:
 * все три лечатся правкой `.env` или окна модели, и человек должен уйти
 * отсюда со строкой, которую можно вписать, а не с догадкой.
 */
function Advice({ rows }: { rows: ParsedReason[] }) {
  const advice = [...new Set(rows.map((row) => FAILURE_ADVICE[row.detail]))].filter(
    (text): text is string => text !== undefined,
  );

  if (advice.length === 0) {
    return null;
  }

  return (
    <div className="rule border-t pt-3">
      <p className="case-label">что с этим делать</p>
      <ul className="mt-1.5 space-y-1.5">
        {advice.map((text) => (
          <li key={text} className="text-[14px] leading-relaxed text-paper-dim">
            {text}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReasonTable({ rows }: { rows: ParsedReason[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="rule border-b">
            <th className="case-label py-1.5 pr-4 font-normal">файл</th>
            <th className="case-label py-1.5 pr-4 font-normal">причина</th>
            <th className="case-label py-1.5 pr-4 font-normal">модель</th>
            <th className="case-label py-1.5 pr-4 text-right font-normal">промпт, токенов</th>
            <th className="case-label py-1.5 text-right font-normal">упёрлось в</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${index}-${row.path}`} className="align-top">
              <td className="py-2 pr-4">
                <span className="file-chip">{row.path}</span>
              </td>
              {row.model === null ? (
                <td className="py-2 text-[14px] text-paper-dim" colSpan={4}>
                  {row.detail}
                </td>
              ) : (
                <>
                  <td className="py-2 pr-4 text-[14px] text-paper-dim">{row.detail}</td>
                  <td className="py-2 pr-4 font-mono text-[13px] text-paper-dim">{row.model}</td>
                  <td
                    className="py-2 pr-4 text-right font-mono text-[14px] text-critical"
                    title={
                      row.prompt === null
                        ? "Размер подсказки называет только сервер и только когда она не поместилась в окно"
                        : undefined
                    }
                  >
                    {row.prompt ?? "—"}
                  </td>
                  <td className="py-2 text-right font-mono text-[14px] text-paper">
                    {row.limit ?? "—"}
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface ParsedReason {
  path: string | null;
  detail: string;
  model: string | null;
  prompt: string | null;
  limit: string | null;
}

function parseReason(line: string): ParsedReason {
  const separator = line.indexOf(": ");
  const path = separator === -1 ? null : line.slice(0, separator);

  if (path === null || path.includes(" ")) {
    return { path: null, detail: line, model: null, prompt: null, limit: null };
  }

  const detail = line.slice(separator + 2);
  for (const { pattern, reason, read } of FAILURE_PATTERNS) {
    const match = pattern.exec(detail);
    if (match !== null) {
      return { path, detail: reason, ...read(match) };
    }
  }

  return { path, detail, model: null, prompt: null, limit: null };
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="case-label">{label}</dt>
      <dd className="font-mono text-[14px] text-paper">{value}</dd>
    </div>
  );
}

/**
 * Считает время сам, а не при получении ответа сервера.
 *
 * Опрос прогона возвращает те же данные, пока он не закончился, и React не
 * перерисовывает компонент — секунды замирали до перезагрузки страницы.
 *
 * Это время текущей попытки; прошлые приходят с сервера отдельным полем
 * и складываются с ним. После продолжения счётчик обязан идти дальше,
 * а не начинаться заново: человек спрашивает, сколько идёт дело.
 */
function useElapsedSeconds(startedAt: string | null): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  if (!startedAt) {
    return 0;
  }
  return Math.max(0, Math.round((now - new Date(startedAt).getTime()) / 1000));
}

function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${seconds} с`;
  }
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest === 0 ? `${minutes} мин` : `${minutes} мин ${rest} с`;
}
