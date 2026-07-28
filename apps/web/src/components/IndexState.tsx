import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/api/client";
import type { IndexState as State } from "@/api/types";
import { formatDateTime, shortSha } from "@/lib/format";

interface Props {
  repositoryId: string;
}

const WORKER_HINT = "uv run arq ducktective.indexer.worker.WorkerSettings";

/**
 * Состояние индекса репозитория.
 *
 * Показывается всегда, а не только при ошибке: без индекса ревью работает
 * по одному диффу и находит вдвое меньше, и человек должен понимать,
 * на что смотрит.
 */
export function IndexState({ repositoryId }: Props) {
  const queryClient = useQueryClient();
  const [isQueued, setIsQueued] = useState(false);

  const state = useQuery({
    queryKey: ["index", repositoryId],
    queryFn: () => api.getIndexState(repositoryId),
    enabled: Boolean(repositoryId),
    refetchInterval: (query) => (isRunning(query.state.data) || isQueued ? 2000 : false),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["index", repositoryId] });

  const start = useMutation({
    mutationFn: () => api.startIndexing(repositoryId),
    onSuccess: async () => {
      setIsQueued(true);
      await invalidate();
    },
  });

  const cancel = useMutation({
    mutationFn: () => api.cancelIndexing(repositoryId),
    onSuccess: async () => {
      setIsQueued(false);
      await invalidate();
    },
  });

  const data = state.data;
  const running = isRunning(data);

  useEffect(() => {
    if (running || data?.snapshot_id) {
      setIsQueued(false);
    }
  }, [running, data?.snapshot_id]);

  if (!repositoryId || state.isPending) {
    return null;
  }

  const busy = running || start.isPending;

  return (
    <div className="border border-tweed-dim bg-ink-sunken px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="case-label">индекс</span>
        <span className="font-mono text-[13px] text-paper-dim">{describe(data, busy)}</span>

        {running ? (
          <CancelButton onCancel={() => cancel.mutate()} isPending={cancel.isPending} />
        ) : (
          <button
            type="button"
            onClick={() => start.mutate()}
            disabled={busy}
            className="ml-auto rounded-case border border-tweed-dim px-3 py-1 font-mono text-[12px] tracking-wide text-paper-dim transition-colors hover:border-brass hover:text-brass disabled:opacity-40"
          >
            {busy ? "ставлю в очередь…" : data?.is_ready ? "обновить" : "проиндексировать"}
          </button>
        )}
      </div>

      {running ? <Progress state={data} /> : null}

      {data?.status === "failed" && data.failure_reason ? (
        <p className="mt-2 text-[13px] text-critical">{data.failure_reason}</p>
      ) : null}

      {data?.status === "cancelled" ? (
        <p className="mt-2 text-[13px] text-paper-dim">
          Прошлая сборка отменена — записанное откатилось, индекс не изменился.
        </p>
      ) : null}

      {isQueued && !running ? (
        <p className="mt-2 text-[13px] text-paper-dim">
          Задача поставлена в очередь. Если ничего не происходит, воркер индексации
          не запущен: <code className="text-brass">{WORKER_HINT}</code>
        </p>
      ) : null}
    </div>
  );
}

interface CancelProps {
  onCancel: () => void;
  isPending: boolean;
}

/**
 * Кнопка сборки превращается в отмену при наведении.
 *
 * Отдельная кнопка рядом провоцировала бы промах: во время долгой сборки
 * взгляд прикован именно к этому месту.
 */
function CancelButton({ onCancel, isPending }: CancelProps) {
  return (
    <button
      type="button"
      onClick={onCancel}
      disabled={isPending}
      className="group/cancel ml-auto rounded-case border border-tweed-dim px-3 py-1 font-mono text-[12px] tracking-wide text-paper-dim transition-colors hover:border-dismissed hover:text-dismissed disabled:opacity-40"
    >
      <span className="group-hover/cancel:hidden">{isPending ? "отменяю…" : "собирается…"}</span>
      <span className="hidden group-hover/cancel:inline">отменить</span>
    </button>
  );
}

interface ProgressProps {
  state: State | undefined;
}

/**
 * Ход сборки.
 *
 * Шкала показывает только разбор файлов — он заканчивается задолго до конца
 * работы. Дальше идут запись и построение графа, у которых нет знаменателя,
 * поэтому вместо процентов там название этапа: доведённая до ста процентов
 * и застывшая шкала выглядит поломкой.
 */
function Progress({ state }: ProgressProps) {
  const stage = state?.stage ?? "parsing";
  const title = state?.stage_title ?? "разбираю файлы";
  const total = state?.stats?.files_total ?? 0;
  const done = (state?.stats?.files_parsed ?? 0) + (state?.stats?.files_reused ?? 0);
  const isParsing = stage === "parsing" && total > 0;
  const percent = isParsing ? Math.min(100, Math.round((done / total) * 100)) : 0;

  return (
    <div className="mt-3">
      <div className="h-1 overflow-hidden bg-tweed-dim">
        {isParsing ? (
          <div
            className="h-full bg-brass transition-all duration-500"
            style={{ width: `${percent}%` }}
          />
        ) : (
          <div className="h-full w-1/3 animate-pulse bg-brass" />
        )}
      </div>

      <p className="case-label mt-1.5">
        {title}
        {isParsing ? ` · ${done} из ${total} · ${percent}%` : " · это дольше разбора"}
      </p>
    </div>
  );
}

function isRunning(state: State | undefined): boolean {
  return state?.status === "pending" || state?.status === "running";
}

function describe(state: State | undefined, busy: boolean): string {
  if (busy) {
    return "идёт сборка";
  }
  if (state?.status === "failed") {
    return "последняя попытка не удалась";
  }
  if (!state?.is_ready || !state.stats) {
    return "не собран — ревью пойдёт по одному диффу, без окружения";
  }

  const { symbols, chunks, files_total: files } = state.stats;
  const when = state.finished_at ? `, собран ${formatDateTime(state.finished_at)}` : "";
  return `${files} файлов · ${symbols} символов · ${chunks} фрагментов · ревизия ${shortSha(state.commit_sha ?? "")}${when}`;
}
