import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { IndexState } from "@/api/types";

interface Props {
  repositoryId: string;
}

/**
 * Состояние индекса одной строкой — для боковой панели разговора.
 *
 * Полная панель со стадиями, шкалой и удалением живёт на карточке дела:
 * в разговоре она занимала всю ширину и отталкивала вниз то, ради чего
 * страницу открыли. Здесь нужен ответ на один вопрос — можно ли уже
 * спрашивать, — и кнопка на случай «нет».
 */
export function IndexBadge({ repositoryId }: Props) {
  const queryClient = useQueryClient();

  const state = useQuery({
    queryKey: ["index", repositoryId],
    queryFn: () => api.getIndexState(repositoryId),
    enabled: Boolean(repositoryId),
    refetchInterval: (query) => (isBusy(query.state.data) ? 2000 : false),
  });

  const start = useMutation({
    mutationFn: () => api.startIndexing(repositoryId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["index", repositoryId] }),
  });

  if (state.isPending || state.isError) {
    return null;
  }

  const value = state.data;
  const busy = isBusy(value);

  return (
    <div className="space-y-1.5">
      <span className={`status-badge ${value.context_ready || busy ? "status-live" : "status-off"}`}>
        <span className="status-dot" aria-hidden />
        {label(value, busy)}
      </span>
      {value.context_ready || busy ? null : (
        <button
          type="button"
          disabled={start.isPending}
          onClick={() => start.mutate()}
          className="card-action w-full justify-center"
        >
          {start.isPending ? "ставлю в очередь…" : "собрать индекс"}
        </button>
      )}
    </div>
  );
}

function isBusy(state?: IndexState): boolean {
  return state?.status === "running" || state?.status === "pending";
}

function label(state: IndexState, busy: boolean): string {
  if (busy) {
    return state.stage_title ? `индексирую · ${state.stage_title}` : "индексирую";
  }
  if (state.context_ready) {
    const files = state.stats?.files_total;
    return files ? `индекс готов · ${files} файлов` : "индекс готов";
  }
  return "индекса нет";
}
