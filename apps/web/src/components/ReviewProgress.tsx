import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/api/client";
import type { ReviewRun } from "@/api/types";

const AVERAGE_SECONDS_PER_FILE = 25;

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

export function ReviewFailure({ run }: Props) {
  return (
    <section className="border border-critical/40 bg-critical/5 px-5 py-4">
      <h2 className="font-display text-2xl font-semibold text-paper">
        Расследование не удалось
      </h2>
      <p className="mt-2 text-[16px] text-paper-dim">
        {run.failure_reason ??
          "Причина не сохранилась. Загляните в журнал воркера — там будет подробность."}
      </p>
      <RestartButton runId={run.id} />
    </section>
  );
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
