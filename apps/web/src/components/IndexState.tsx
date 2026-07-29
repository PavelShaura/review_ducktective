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
 * Общий вид кнопок панели.
 *
 * Все действия здесь равнозначны по весу, и различать их формой значило бы
 * подсказывать выбор, которого нет: удаление отличается только цветом
 * наведения.
 */
const BUTTON =
  "rounded-case border border-tweed-dim px-3 py-1 font-mono text-[12px] tracking-wide text-paper-dim transition-colors disabled:opacity-40";

/**
 * Состояние индекса репозитория.
 *
 * Сообщение об удалении держится только до начала новой сборки: результат
 * прошлого действия, оставшийся на экране рядом с идущим, читается как
 * относящийся к нему.
 *
 * Показывается всегда, а не только при ошибке: без индекса ревью работает
 * по одному диффу и находит вдвое меньше, и человек должен понимать,
 * на что смотрит.
 *
 * Очередь берётся из состояния снапшота, а не из памяти вкладки: задача
 * ставится вместе с записью в базе, поэтому «в очереди» переживает
 * перезагрузку страницы и честно отличается от «ничего не происходит».
 */
export function IndexState({ repositoryId }: Props) {
  const queryClient = useQueryClient();
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);

  const state = useQuery({
    queryKey: ["index", repositoryId],
    queryFn: () => api.getIndexState(repositoryId),
    enabled: Boolean(repositoryId),
    refetchInterval: (query) =>
      isBusy(query.state.data) || vectorsPending(query.state.data) ? 2000 : false,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["index", repositoryId] });

  const start = useMutation({
    mutationFn: () => api.startIndexing(repositoryId),
    onSuccess: invalidate,
  });

  const cancel = useMutation({
    mutationFn: () => api.cancelIndexing(repositoryId),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: () => api.deleteIndex(repositoryId),
    onSuccess: async () => {
      setIsConfirmingDelete(false);
      await invalidate();
    },
  });

  const data = state.data;

  if (!repositoryId || state.isPending) {
    return null;
  }

  const queued = data?.status === "pending";
  const running = data?.status === "running";
  const busy = queued || running || start.isPending;
  const embedding = vectorsPending(data);
  const hasIndex = Boolean(data?.snapshot_id);

  return (
    <div className="border border-tweed-dim bg-ink-sunken px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="case-label">индекс</span>
        <span className="font-mono text-[13px] text-paper">{describe(data, start.isPending)}</span>
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

      {cancel.data?.cancelled === false ? (
        <p className="mt-2 text-[13px] text-paper-dim">
          Отменять было нечего — сборка успела закончиться.
        </p>
      ) : null}

      {remove.data && !hasIndex && !busy ? (
        <p className="mt-2 text-[13px] text-paper-dim">
          Индекс стёрт: снапшотов удалено {remove.data.removed_snapshots}. Соберите заново,
          чтобы ревью снова видело окружение.
        </p>
      ) : null}

      {data?.is_ready && embedding ? <Vectors state={data} /> : null}

      {data?.embedding_stopped ? (
        <p className="mt-2 text-[13px] text-paper-dim">
          Досчёт векторов остановлен — посчитанное сохранено, остаток доедет при
          следующей сборке. Поиск по смыслу пока неполный.
        </p>
      ) : null}

      {queued ? <Queued state={data} /> : null}

      <div className="mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-tweed-dim pt-3">
        {hasIndex && !busy && !embedding ? (
          <DeleteIndexButton
            isConfirming={isConfirmingDelete}
            onAsk={() => setIsConfirmingDelete(true)}
            onDismiss={() => setIsConfirmingDelete(false)}
            onDelete={() => remove.mutate()}
            isPending={remove.isPending}
          />
        ) : null}

        {queued || running || embedding ? (
          <CancelButton
            onCancel={() => cancel.mutate()}
            isPending={cancel.isPending}
            label={queued ? "в очереди…" : running ? "собирается…" : "считаю векторы…"}
          />
        ) : (
          <button
            type="button"
            onClick={() => start.mutate()}
            disabled={busy}
            className={`${BUTTON} hover:border-brass hover:text-brass`}
          >
            {start.isPending
              ? "ставлю в очередь…"
              : data?.is_ready
                ? "обновить"
                : "проиндексировать"}
          </button>
        )}
      </div>
    </div>
  );
}

interface DeleteProps {
  isConfirming: boolean;
  onAsk: () => void;
  onDismiss: () => void;
  onDelete: () => void;
  isPending: boolean;
}

/**
 * Удаление индекса.
 *
 * Выглядит кнопкой, а не подписью: рядом стоит «обновить», и действие
 * с необратимыми последствиями не должно читаться как пояснение к соседу.
 *
 * Подтверждение спрашивается прямо в кнопке и спрашивает ровно о том, что
 * нажали, — о стирании. Пересборка после него возможна, но это следующий
 * шаг человека, а не смысл нажатия.
 */
function DeleteIndexButton({ isConfirming, onAsk, onDismiss, onDelete, isPending }: DeleteProps) {
  if (!isConfirming) {
    return (
      <button
        type="button"
        onClick={onAsk}
        className={`${BUTTON} hover:border-dismissed hover:text-dismissed`}
      >
        удалить индекс
      </button>
    );
  }

  return (
    <span className="flex items-center gap-2">
      <span className="case-label text-dismissed">стереть индекс целиком?</span>
      <button
        type="button"
        onClick={onDelete}
        disabled={isPending}
        className={`${BUTTON} border-dismissed text-dismissed hover:bg-dismissed hover:text-ink disabled:opacity-50`}
      >
        {isPending ? "стираю…" : "стереть"}
      </button>
      <button
        type="button"
        onClick={onDismiss}
        className={`${BUTTON} hover:border-paper hover:text-paper`}
      >
        отмена
      </button>
    </span>
  );
}

interface CancelProps {
  onCancel: () => void;
  isPending: boolean;
  label: string;
}

/**
 * Кнопка сборки превращается в отмену при наведении.
 *
 * Отдельная кнопка рядом провоцировала бы промах: во время долгой сборки
 * взгляд прикован именно к этому месту.
 */
function CancelButton({ onCancel, isPending, label }: CancelProps) {
  return (
    <button
      type="button"
      onClick={onCancel}
      disabled={isPending}
      className={`group/cancel ${BUTTON} hover:border-dismissed hover:text-dismissed`}
    >
      <span className="group-hover/cancel:hidden">{isPending ? "отменяю…" : label}</span>
      <span className="hidden group-hover/cancel:inline">отменить</span>
    </button>
  );
}

interface ProgressProps {
  state: State | undefined;
}

/**
 * Что подразумевается под каждым этапом.
 *
 * Названия этапов коротки и потому загадочны: «сохраняю символы» ничего
 * не говорит о том, почему это долго. Пояснение снимает главный вопрос
 * человека у экрана — идёт работа или всё встало.
 */
const STAGE_NOTES: Record<string, string> = {
  parsing: "читаю изменившиеся файлы и разбираю их на символы",
  storing: "записываю символы и фрагменты в базу пачками по 200 файлов",
  linking: "связываю вызовы с определениями по всей кодовой базе",
  embedding: "считаю векторы для поиска по смыслу — обращается к модели",
};

/**
 * Ход сборки.
 *
 * У каждого этапа своя шкала и свой знаменатель: разбор считает файлы дерева,
 * запись — только изменившиеся. Общей шкалы нет намеренно, доля этапов
 * в общем времени непредсказуема и зависит от репозитория.
 *
 * Там, где знаменателя нет вовсе, показывается время ожидания: застывшая
 * шкала выглядит поломкой, а идущий счётчик — работой.
 */
function Progress({ state }: ProgressProps) {
  const stage = state?.stage ?? "parsing";
  const title = state?.stage_title ?? "разбираю файлы";
  const measured = measure(state);

  return (
    <div className="mt-3">
      <div className="h-1 overflow-hidden bg-tweed-dim">
        {measured ? (
          <div
            className="h-full bg-brass transition-all duration-500"
            style={{ width: `${measured.percent}%` }}
          />
        ) : (
          <div className="h-full w-1/3 animate-pulse bg-brass" />
        )}
      </div>

      <p className="case-label mt-1.5">
        {title}
        {measured ? ` · ${measured.done} из ${measured.total} · ${measured.percent}%` : ""}
        <Elapsed since={state?.started_at ?? null} />
      </p>

      {STAGE_NOTES[stage] ? (
        <p className="mt-1 text-[12px] text-paper-dim">{STAGE_NOTES[stage]}</p>
      ) : null}
    </div>
  );
}

interface Measured {
  done: number;
  total: number;
  percent: number;
}

function measure(state: State | undefined): Measured | null {
  const stats = state?.stats;
  if (!stats) {
    return null;
  }

  const [done, total] =
    state?.stage === "storing"
      ? [stats.files_stored, stats.files_parsed]
      : [stats.files_parsed + stats.files_reused, stats.files_total];

  if (total <= 0) {
    return null;
  }
  return { done, total, percent: Math.min(100, Math.round((done / total) * 100)) };
}

interface VectorsProps {
  state: State;
}

/**
 * Досчёт векторов после того, как символы и граф уже готовы.
 *
 * Знаменатель здесь известен, в отличие от связывания, поэтому шкала честная.
 * Без неё индекс выглядит собранным, хотя поиск по смыслу ещё не работает —
 * и человек делает вывод о качестве по неполному индексу.
 *
 * Рядом сказано, из чего состоит индекс: два слоя видны только изнутри,
 * а снаружи «векторы 12%» не объясняет ни что уже работает, ни чего ждать.
 */
function Vectors({ state }: VectorsProps) {
  const { chunks, embedded } = state.vectors;
  const percent = Math.min(100, Math.round((embedded / chunks) * 100));

  return (
    <div className="mt-3">
      <div className="h-1 overflow-hidden bg-tweed-dim">
        <div
          className="h-full bg-brass transition-all duration-500"
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="case-label mt-1.5">
        символы и граф готовы · векторы {embedded} из {chunks} · {percent}%
      </p>
      <p className="mt-1 text-[12px] leading-relaxed text-paper-dim">
        Индекс складывается из двух слоёв. Первый — символы и граф вызовов, он уже
        готов: по нему ревью отвечает, кто вызывает изменённый код и что покрывает
        эти строки. Второй — векторы, они дают поиск по смыслу, когда нужное место
        называется иначе, чем запрос. Пока векторы считаются, ревью опирается
        на слова и граф: оно работает, но похожие места находит хуже.
      </p>
    </div>
  );
}

interface QueuedProps {
  state: State | undefined;
}

/**
 * Почему задача стоит в очереди.
 *
 * Ожидание бывает двух видов, и лечатся они противоположно: занятый воркер
 * требует терпения, отсутствующий — запуска. Один и тот же совет на оба
 * случая предлагает запускать то, что уже работает.
 */
function Queued({ state }: QueuedProps) {
  if (vectorsPending(state)) {
    return (
      <p className="mt-2 text-[13px] text-paper-dim">
        Воркер досчитывает векторы прошлой сборки — задача пойдёт следом.
      </p>
    );
  }

  return (
    <p className="mt-2 text-[13px] text-paper-dim">
      Задача в очереди. Если она не двигается, воркер индексации не запущен:{" "}
      <code className="text-brass">{WORKER_HINT}</code>
    </p>
  );
}

interface ElapsedProps {
  since: string | null;
}

/**
 * Сколько идёт сборка.
 *
 * Единственное, что честно показывает движение на этапах без знаменателя.
 * Человеку нужно знать не «сколько осталось», а «сколько я уже жду»:
 * первое неизвестно, второе снимает подозрение, что процесс встал.
 */
function Elapsed({ since }: ElapsedProps) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  if (!since) {
    return null;
  }

  const seconds = Math.max(0, Math.floor((now - new Date(since).getTime()) / 1000));
  return <span> · идёт {formatDuration(seconds)}</span>;
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  if (minutes < 1) {
    return `${seconds} с`;
  }
  if (minutes < 60) {
    return `${minutes} мин ${String(seconds % 60).padStart(2, "0")} с`;
  }
  return `${Math.floor(minutes / 60)} ч ${String(minutes % 60).padStart(2, "0")} мин`;
}

function isBusy(state: State | undefined): boolean {
  return state?.status === "pending" || state?.status === "running";
}

function describe(state: State | undefined, isStarting: boolean): string {
  if (isStarting) {
    return "ставлю в очередь";
  }
  if (state?.status === "pending") {
    return "ждёт воркера";
  }
  if (state?.status === "running") {
    return "идёт сборка";
  }
  if (state?.status === "failed") {
    return "последняя попытка не удалась";
  }
  if (!state?.is_ready || !state.stats) {
    return "не собран — ревью пойдёт по одному диффу, без окружения";
  }

  const when = state.finished_at ? ` · собран ${formatDateTime(state.finished_at)}` : "";
  return `${state.stats.files_total} файлов · ревизия ${shortSha(state.commit_sha ?? "")}${when}`;
}

/**
 * Досчитаны ли векторы.
 *
 * Снапшот помечается готовым до них: символы и граф полезны сами по себе,
 * а модель может быть недоступна. Поэтому «собран» и «поиск по смыслу
 * работает» — разные состояния, и второе надо показывать отдельно.
 */
function vectorsPending(state: State | undefined): boolean {
  const vectors = state?.vectors;
  return Boolean(
    vectors && vectors.chunks > 0 && vectors.embedded < vectors.chunks && !state?.embedding_stopped,
  );
}
