import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { api } from "@/api/client";
import type { IndexState } from "@/api/types";
import { stageTitle } from "@/lib/stage";

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
  const { t } = useTranslation();

  if (state.isPending || state.isError) {
    return null;
  }

  const value = state.data;
  const busy = isBusy(value);

  return (
    <span className={`status-badge ${value.context_ready || busy ? "status-live" : "status-off"}`}>
      <span className="status-dot" aria-hidden />
      {label(t, value, busy)}
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
  const { t } = useTranslation();

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
      {start.isPending ? t("indexBadge.queueing") : t("indexBadge.build")}
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

function label(t: TFunction, state: IndexState, busy: boolean): string {
  if (busy) {
    const stage = stageTitle(t, state);
    return stage ? t("indexBadge.indexingStage", { stage }) : t("indexBadge.indexing");
  }
  if (state.context_ready) {
    const files = state.totals.files;
    return files ? t("indexBadge.readyFiles", { count: files }) : t("indexBadge.ready");
  }
  return t("indexBadge.none");
}
