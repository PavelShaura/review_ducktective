import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { IndexState } from "@/api/types";

interface Props {
  repositoryId: string;
}

/**
 * Состояние индекса одной строкой.
 *
 * Полная панель со стадиями, шкалой и удалением живёт на карточке дела:
 * в разговоре и в списке индексов она занимала бы всю ширину и отталкивала
 * вниз то, ради чего страницу открыли. Здесь нужен ответ на один вопрос —
 * можно ли уже спрашивать.
 *
 * Только бейдж, без кнопки: он встаёт в строку с названием репозитория,
 * а кнопка рядом с ним разрывала бы эту строку. Действие живёт отдельно —
 * `IndexAction`, — и каждая страница ставит его туда, где оно уместно.
 */
export function IndexBadge({ repositoryId }: Props) {
  const state = useIndexState(repositoryId);

  if (state.isPending || state.isError) {
    return null;
  }

  const value = state.data;
  const busy = isBusy(value);

  return (
    <span className={`status-badge ${value.context_ready || busy ? "status-live" : "status-off"}`}>
      <span className="status-dot" aria-hidden />
      {label(value, busy)}
    </span>
  );
}

/**
 * Кнопка сборки — там, где индекса ещё нет.
 *
 * Пока сборка идёт или индекс готов, кнопки нет вовсе: обновлять и удалять
 * ходят в полную панель, а здесь нужен один шаг для того, у кого индекса
 * не было никогда.
 */
export function IndexAction({ repositoryId }: Props) {
  const queryClient = useQueryClient();
  const state = useIndexState(repositoryId);

  const start = useMutation({
    mutationFn: () => api.startIndexing(repositoryId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["index", repositoryId] }),
  });

  if (state.isPending || state.isError) {
    return null;
  }

  if (state.data.context_ready || isBusy(state.data)) {
    return null;
  }

  return (
    <button
      type="button"
      disabled={start.isPending}
      onClick={() => start.mutate()}
      className={`card-action card-action-primary ${start.isPending ? "card-action-busy" : ""}`}
    >
      {start.isPending ? "ставлю в очередь…" : "собрать индекс"}
    </button>
  );
}

function useIndexState(repositoryId: string) {
  return useQuery({
    queryKey: ["index", repositoryId],
    queryFn: () => api.getIndexState(repositoryId),
    enabled: Boolean(repositoryId),
    refetchInterval: (query) => (isBusy(query.state.data) ? 2000 : false),
  });
}

function isBusy(state?: IndexState): boolean {
  return state?.status === "running" || state?.status === "pending";
}

function label(state: IndexState, busy: boolean): string {
  if (busy) {
    return state.stage_title ? `индексирую · ${state.stage_title}` : "индексирую";
  }
  if (state.context_ready) {
    const files = state.totals.files;
    return files ? `индекс готов · ${files} файлов` : "индекс готов";
  }
  return "индекса нет";
}
