import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { api } from "@/api/client";
import type { DegradationKind, NodeDegradation, ReviewRun } from "@/api/types";
import { stageTitle } from "@/lib/stage";

const AVERAGE_SECONDS_PER_FILE = 240;

const REVIEWER_NAME_PREFIX = "reviewer:";

/**
 * Причины разделены переносом строки, но в делах, заведённых раньше, они
 * склеены точкой с запятой. Она разделяет только там, где дальше начинается
 * путь: внутри текста ошибки точка с запятой ничего не разрывает.
 */
const REASON_SEPARATOR = /\n|;\s+(?=\S+:\s)/;

/** Во что упёрлась модель: показывается своей подписью и числом. */
interface Limit {
  kind: "window" | "answer" | "timeout";
  value: string;
}

/**
 * Сбои модели, у которых есть разбираемая структура. Порядок важен: строка
 * проверяется до первого совпадения. Всё, что не совпало, показывается текстом.
 *
 * Образцы — формулировки сервера, они на русском независимо от языка
 * интерфейса: причина хранится в базе текстом, и разбирается тот текст,
 * который туда записан. Разобранное дальше подписывается по виду сбоя,
 * а вид уже переводится.
 */
const FAILURE_PATTERNS: {
  pattern: RegExp;
  kind: DegradationKind;
  read: (match: RegExpExecArray) => { model: string; prompt: string | null; limit: Limit | null };
}[] = [
  {
    pattern: /модели (\S+): (\d+) токенов при окне (\d+)/,
    kind: "context_overflow",
    read: (match) => ({
      model: match[1]!,
      prompt: match[2]!,
      limit: { kind: "window", value: match[3]! },
    }),
  },
  {
    pattern: /Модель (\S+) исчерпала лимит ответа в (\d+) токенов/,
    kind: "output_exhausted",
    read: (match) => ({ model: match[1]!, prompt: null, limit: { kind: "answer", value: match[2]! } }),
  },
  {
    /* Формулировка до 2026-08-02: дела, заведённые раньше, лежат в базе с ней. */
    pattern: /Модель (\S+) оборвала ответ на лимите (\d+) токенов/,
    kind: "output_exhausted",
    read: (match) => ({ model: match[1]!, prompt: null, limit: { kind: "answer", value: match[2]! } }),
  },
  {
    pattern: /Модель (\S+) не ответила за (\d+) с/,
    kind: "timeout",
    read: (match) => ({ model: match[1]!, prompt: null, limit: { kind: "timeout", value: match[2]! } }),
  },
  {
    pattern: /Модель (\S+) ограничивает частоту/,
    kind: "rate_limited",
    read: (match) => ({ model: match[1]!, prompt: null, limit: null }),
  },
];

/** Виды сбоя, у которых есть совет. Совет привязан к виду, а не к формулировке. */
const ADVISED_KINDS = [
  "context_overflow",
  "output_exhausted",
  "timeout",
  "rate_limited",
  "context_unavailable",
] as const;

type AdvisedKind = (typeof ADVISED_KINDS)[number];

function isAdvised(kind: DegradationKind | null): kind is AdvisedKind {
  return kind !== null && (ADVISED_KINDS as readonly string[]).includes(kind);
}

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
function useIndexingForRun(run: ReviewRun, t: TFunction): string | null {
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
    return t("review.indexWaiting");
  }
  if (state.status === "running") {
    return stageTitle(t, state) ?? t("review.indexBuilding");
  }
  return null;
}

/**
 * Пока прогон не завершён, находок в базе нет вообще: они записываются одной
 * транзакцией в конце. Показывать «замечаний нет» до этого момента — врать.
 */
export function ReviewProgress({ run }: Props) {
  const { t } = useTranslation();
  const current = useElapsedSeconds(run.started_at);
  const elapsed = Math.round(run.duration_ms / 1000) + current;
  const expected = run.files.length * AVERAGE_SECONDS_PER_FILE;
  const indexing = useIndexingForRun(run, t);

  return (
    <section className="border border-brass/40 bg-brass/5 px-5 py-4">
      <div className="flex items-baseline gap-3">
        <span aria-hidden className="animate-pulse text-brass">
          ●
        </span>
        <h2 className="font-display text-2xl font-semibold text-paper">
          {indexing ? t("review.titleIndexing") : t("review.titleRunning")}
        </h2>
      </div>

      <p className="mt-2 text-[16px] text-paper-dim">
        {indexing
          ? t("review.bodyIndexing", { stage: indexing })
          : t("review.bodyRunning", { count: run.files.length })}
      </p>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <dl className="flex flex-wrap gap-x-8 gap-y-1">
          <Fact label={t("review.elapsed")} value={formatDuration(t, elapsed)} />
          <Fact
            label={t("review.expected")}
            value={t("review.about", { duration: formatDuration(t, expected) })}
          />
        </dl>
        <StopButton runId={run.id} />
      </div>
    </section>
  );
}

function StopButton({ runId }: { runId: string }) {
  const queryClient = useQueryClient();
  const { t } = useTranslation();
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
      {stop.isPending ? t("review.stopping") : t("review.stop")}
    </button>
  );
}

export function ReviewCancelled({ run }: Props) {
  const { t } = useTranslation();
  return (
    <section className="border border-paper-dim/30 bg-paper/5 px-5 py-4">
      <h2 className="font-display text-2xl font-semibold text-paper">{t("review.cancelledTitle")}</h2>
      <p className="mt-2 text-[16px] text-paper-dim">{t("review.cancelledBody")}</p>
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
  const { t } = useTranslation();
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
        {resume.isPending ? t("review.resuming") : t("review.resume")}
      </button>
      <button
        type="button"
        onClick={() => restart.mutate()}
        disabled={busy}
        className="case-label border border-paper-dim/40 px-4 py-1.5 text-paper-dim transition hover:border-brass/60 hover:text-brass disabled:opacity-50"
      >
        {restart.isPending ? t("review.restarting") : t("review.restart")}
      </button>
      {restart.isError || resume.isError ? (
        <p className="case-label w-full text-critical">{t("review.actionFailed")}</p>
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
  const { t } = useTranslation();
  if (!run.failure_reason && run.degradations.length === 0) {
    return null;
  }

  const filesWereLost =
    Boolean(run.failure_reason) || run.degradations.some((mark) => mark.stage === "review");

  return (
    <section className="border border-brass/50 bg-brass/10 px-5 py-4">
      <h2 className="font-display text-2xl font-semibold text-paper">
        {filesWereLost ? t("review.degradedPartial") : t("review.degradedNoContext")}
      </h2>
      <Failures run={run} />
    </section>
  );
}

export function ReviewFailure({ run }: Props) {
  const { t } = useTranslation();
  return (
    <section className="border-2 border-critical/70 bg-critical/10 px-5 py-4">
      <span className="stamp inline-block text-[12px] text-critical">{t("review.failStamp")}</span>
      <h2 className="mt-2 font-display text-3xl font-semibold text-critical">
        {t("review.failedTitle")}
      </h2>
      {run.failure_reason || run.degradations.length > 0 ? (
        <Failures run={run} />
      ) : (
        <p className="mt-2 text-[16px] text-paper-dim">
          {t("review.noReason")}
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
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="rule border-b">
            <th className="case-label py-1.5 pr-4 font-normal">{t("review.table.file")}</th>
            <th className="case-label py-1.5 pr-4 font-normal">{t("review.table.who")}</th>
            <th className="case-label py-1.5 pr-4 font-normal">{t("review.table.reason")}</th>
            <th className="case-label py-1.5 font-normal">{t("review.table.model")}</th>
          </tr>
        </thead>
        <tbody>
          {marks.map((mark, index) => (
            <tr key={`${index}-${mark.file_path}`} className="align-top">
              <td className="py-2 pr-4">
                <span className="file-chip">{mark.file_path}</span>
              </td>
              <td className="py-2 pr-4 text-[14px] text-paper-dim">{actorOf(t, mark)}</td>
              <td className="py-2 pr-4">
                <span className="text-[14px] text-paper">{t(`review.kind.${mark.kind}`)}</span>
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
  return <AdviceList kinds={marks.map((mark) => mark.kind)} />;
}

/**
 * Что делать с этими сбоями. Причина названа кодом настройки, а не намёком:
 * все они лечатся правкой `.env` или окна модели, и человек должен уйти
 * отсюда со строкой, которую можно вписать, а не с догадкой.
 */
function AdviceList({ kinds }: { kinds: (DegradationKind | null)[] }) {
  const { t } = useTranslation();
  const advised = [...new Set(kinds.filter(isAdvised))];

  if (advised.length === 0) {
    return null;
  }

  return (
    <div className="rule border-t pt-3">
      <p className="case-label">{t("review.whatToDo")}</p>
      <ul className="mt-1.5 space-y-1.5">
        {advised.map((kind) => (
          <li key={kind} className="text-[14px] leading-relaxed text-paper-dim">
            {t(`review.advice.${kind}`)}
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
function actorOf(t: TFunction, mark: NodeDegradation): string {
  if (mark.reviewer) {
    return mark.reviewer.replace(REVIEWER_NAME_PREFIX, "");
  }
  return t(`review.stage.${mark.stage}`);
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
      <AdviceList kinds={failures.map((row) => row.kind)} />
    </div>
  );
}

function ReasonTable({ rows }: { rows: ParsedReason[] }) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="rule border-b">
            <th className="case-label py-1.5 pr-4 font-normal">{t("review.table.file")}</th>
            <th className="case-label py-1.5 pr-4 font-normal">{t("review.table.reason")}</th>
            <th className="case-label py-1.5 pr-4 font-normal">{t("review.table.model")}</th>
            <th className="case-label py-1.5 pr-4 text-right font-normal">
              {t("review.table.prompt")}
            </th>
            <th className="case-label py-1.5 text-right font-normal">{t("review.table.limit")}</th>
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
                  <td className="py-2 pr-4 text-[14px] text-paper-dim">
                    {row.kind ? t(`review.kind.${row.kind}`) : row.detail}
                  </td>
                  <td className="py-2 pr-4 font-mono text-[13px] text-paper-dim">{row.model}</td>
                  <td
                    className="py-2 pr-4 text-right font-mono text-[14px] text-critical"
                    title={row.prompt === null ? t("review.promptUnknown") : undefined}
                  >
                    {row.prompt ?? "—"}
                  </td>
                  <td className="py-2 text-right font-mono text-[14px] text-paper">
                    {row.limit
                      ? t(`review.limit.${row.limit.kind}`, { value: row.limit.value })
                      : "—"}
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
  /** Текст причины как записан; при узнанном виде сбоя показывается его подпись. */
  detail: string;
  kind: DegradationKind | null;
  model: string | null;
  prompt: string | null;
  limit: Limit | null;
}

function parseReason(line: string): ParsedReason {
  const separator = line.indexOf(": ");
  const path = separator === -1 ? null : line.slice(0, separator);

  if (path === null || path.includes(" ")) {
    return { path: null, detail: line, kind: null, model: null, prompt: null, limit: null };
  }

  const detail = line.slice(separator + 2);
  for (const { pattern, kind, read } of FAILURE_PATTERNS) {
    const match = pattern.exec(detail);
    if (match !== null) {
      return { path, detail, kind, ...read(match) };
    }
  }

  return { path, detail, kind: null, model: null, prompt: null, limit: null };
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

function formatDuration(t: TFunction, seconds: number): string {
  if (seconds < 60) {
    return t("duration.seconds", { count: seconds });
  }
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest === 0
    ? t("duration.minutes", { count: minutes })
    : t("duration.minutesSeconds", { minutes, seconds: rest });
}
