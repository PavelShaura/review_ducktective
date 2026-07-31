import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/api/client";
import type { ReviewRun } from "@/api/types";

const AVERAGE_SECONDS_PER_FILE = 25;

/**
 * Причины разделены переносом строки, но в делах, заведённых раньше, они
 * склеены точкой с запятой. Она разделяет только там, где дальше начинается
 * путь: внутри текста ошибки точка с запятой ничего не разрывает.
 */
const REASON_SEPARATOR = /\n|;\s+(?=\S+:\s)/;

/** Разбирает сообщение LlmContextOverflowError на модель, размер промпта и окно. */
const CONTEXT_OVERFLOW_PATTERN = /модели (\S+): (\d+) токенов при окне (\d+)/;

interface Props {
  run: ReviewRun;
}

/**
 * Пока прогон не завершён, находок в базе нет вообще: они записываются одной
 * транзакцией в конце. Показывать «замечаний нет» до этого момента — врать.
 */
export function ReviewProgress({ run }: Props) {
  const elapsed = useElapsedSeconds(run.started_at);
  const expected = run.files.length * AVERAGE_SECONDS_PER_FILE;

  return (
    <section className="border border-brass/40 bg-brass/5 px-5 py-4">
      <div className="flex items-baseline gap-3">
        <span aria-hidden className="animate-pulse text-brass">
          ●
        </span>
        <h2 className="font-display text-2xl font-semibold text-paper">Расследование идёт</h2>
      </div>

      <p className="mt-2 text-[16px] text-paper-dim">
        Модель читает {run.files.length} файл(ов) по очереди. Замечания появятся сразу все,
        когда прогон закончится.
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
        и остался на месте — расследование можно начать сначала.
      </p>
      <RestartButton runId={run.id} />
    </section>
  );
}

function RestartButton({ runId }: { runId: string }) {
  const queryClient = useQueryClient();
  const restart = useMutation({
    mutationFn: () => api.restartRun(runId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["run", runId] }),
  });

  return (
    <div className="mt-4">
      <button
        type="button"
        onClick={() => restart.mutate()}
        disabled={restart.isPending}
        className="case-label border border-brass/50 px-4 py-1.5 text-brass transition hover:bg-brass/10 disabled:opacity-50"
      >
        {restart.isPending ? "поднимаю дело…" : "расследовать заново"}
      </button>
      {restart.isError ? (
        <p className="case-label mt-2 text-critical">не вышло — проверьте, что сервис на месте</p>
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
  if (!run.failure_reason) {
    return null;
  }

  return (
    <section className="border border-brass/50 bg-brass/10 px-5 py-4">
      <h2 className="font-display text-2xl font-semibold text-paper">
        Расследование прошло не полностью
      </h2>
      <Reasons text={run.failure_reason} />
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
      {run.failure_reason ? (
        <Reasons text={run.failure_reason} />
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
            <th className="case-label py-1.5 pr-4 text-right font-normal">токенов</th>
            <th className="case-label py-1.5 text-right font-normal">окно</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${index}-${row.path}`} className="align-top">
              <td className="py-2 pr-4">
                <span className="file-chip">{row.path}</span>
              </td>
              {row.tokens === null ? (
                <td className="py-2 text-[14px] text-paper-dim" colSpan={4}>
                  {row.detail}
                </td>
              ) : (
                <>
                  <td className="py-2 pr-4 text-[14px] text-paper-dim">{row.detail}</td>
                  <td className="py-2 pr-4 font-mono text-[13px] text-paper-dim">{row.model}</td>
                  <td className="py-2 pr-4 text-right font-mono text-[14px] text-critical">
                    {row.tokens}
                  </td>
                  <td className="py-2 text-right font-mono text-[14px] text-paper">{row.window}</td>
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
  tokens: string | null;
  window: string | null;
}

function parseReason(line: string): ParsedReason {
  const separator = line.indexOf(": ");
  const path = separator === -1 ? null : line.slice(0, separator);

  if (path === null || path.includes(" ")) {
    return { path: null, detail: line, model: null, tokens: null, window: null };
  }

  const detail = line.slice(separator + 2);
  const overflow = CONTEXT_OVERFLOW_PATTERN.exec(detail);
  const [, model, tokens, window] = overflow ?? [];
  if (model === undefined || tokens === undefined || window === undefined) {
    return { path, detail, model: null, tokens: null, window: null };
  }

  return { path, detail: "не поместился в окно", model, tokens, window };
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
