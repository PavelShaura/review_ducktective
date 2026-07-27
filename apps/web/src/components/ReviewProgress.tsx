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
  const elapsed = elapsedSeconds(run.started_at);
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
        когда прогон закончится — промежуточных результатов не бывает.
      </p>

      <dl className="mt-3 flex flex-wrap gap-x-8 gap-y-1">
        <Fact label="идёт" value={formatDuration(elapsed)} />
        <Fact label="ожидаемо" value={`около ${formatDuration(expected)}`} />
      </dl>
    </section>
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

function elapsedSeconds(startedAt: string | null): number {
  if (!startedAt) {
    return 0;
  }
  return Math.max(0, Math.round((Date.now() - new Date(startedAt).getTime()) / 1000));
}

function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${seconds} с`;
  }
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest === 0 ? `${minutes} мин` : `${minutes} мин ${rest} с`;
}
