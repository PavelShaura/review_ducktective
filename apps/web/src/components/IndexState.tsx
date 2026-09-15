import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { api } from "@/api/client";
import type { EmbedderChoice, IndexState as State } from "@/api/types";
import { formatDateTime, shortSha } from "@/lib/format";
import { stageTitle } from "@/lib/stage";

interface Props {
  repositoryId: string;
}

const WORKER_HINT = "uv run arq ducktective.indexer.worker.WorkerSettings";

/**
 * Общий вид кнопок панели — тот же, что на карточках подключений и моделей.
 *
 * Действия здесь равнозначны по весу и различаются не формой, а цветом
 * наведения: сборка тянется к латуни, удаление — к тревожному тону.
 * Форма подсказывала бы выбор, которого нет.
 */
const BUTTON = "card-action";

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
  const { t } = useTranslation();

  const state = useQuery({
    queryKey: ["index", repositoryId],
    queryFn: () => api.getIndexState(repositoryId),
    enabled: Boolean(repositoryId),
    refetchInterval: (query) =>
      isBusy(query.state.data) || vectorsAdvancing(query.state.data) ? 2000 : false,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["index", repositoryId] });

  const embedders = useQuery({
    queryKey: ["embedders"],
    queryFn: () => api.listEmbedders(),
    staleTime: 5 * 60 * 1000,
  });
  const [embedder, setEmbedder] = useState<string | null>(null);

  const start = useMutation({
    mutationFn: () =>
      api.startIndexing(repositoryId, "HEAD", embedder ?? data?.embedding_backend ?? undefined),
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
  const embedding = Boolean(data?.is_embedding);
  const incomplete = vectorsPending(data);
  const hasIndex = Boolean(data?.snapshot_id);

  return (
    <div className="rounded-case border border-tweed-dim bg-ink-sunken px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="case-label">{t("index.label")}</span>
        <span className="font-mono text-[13px] text-paper">{describe(t, data, start.isPending)}</span>
      </div>

      {running ? <Progress state={data} /> : null}

      {data?.status === "failed" && data.failure_reason ? (
        <p className="mt-2 text-[13px] text-critical">{data.failure_reason}</p>
      ) : null}

      {data?.status === "cancelled" ? (
        <p className="mt-2 text-[13px] text-paper-dim">
          {t("index.cancelled")}
          {data.context_ready ? t("index.cancelledReady") : t("index.cancelledNone")}
        </p>
      ) : null}

      {cancel.data?.cancelled === false ? (
        <p className="mt-2 text-[13px] text-paper-dim">
          {t("index.nothingToCancel")}
        </p>
      ) : null}

      {remove.data && !hasIndex && !busy ? (
        <p className="mt-2 text-[13px] text-paper-dim">
          {t("index.removed", { count: remove.data.removed_snapshots })}
        </p>
      ) : null}

      {data?.context_ready && (embedding || incomplete) ? <Vectors state={data} /> : null}

      {data?.embedding_stopped ? (
        <p className="mt-2 text-[13px] text-paper-dim">
          {t("index.embeddingStopped")}
        </p>
      ) : null}

      {queued ? <Queued state={data} /> : null}

      {!busy && !embedding && embedders.data && embedders.data.length > 1 ? (
        <EmbedderPicker
          choices={embedders.data}
          value={embedder ?? data?.embedding_backend ?? ""}
          onChange={setEmbedder}
        />
      ) : null}

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
            label={
              queued ? t("index.inQueue") : running ? t("index.building") : t("index.embedding")
            }
          />
        ) : (
          <button
            type="button"
            onClick={() => start.mutate()}
            disabled={busy}
            className={`${BUTTON} card-action-primary ${busy ? "card-action-busy" : ""}`}
          >
            {start.isPending
              ? t("index.queueing")
              : data?.is_ready
                ? t("index.refresh")
                : t("index.build")}
          </button>
        )}
      </div>
    </div>
  );
}

interface EmbedderPickerProps {
  choices: EmbedderChoice[];
  value: string;
  onChange: (key: string) => void;
}

/**
 * Каким сервером считать векторы.
 *
 * Показывается только когда серверов больше одного: выбор из одного —
 * не выбор. Пояснение к выбранному стоит прямо под списком, а не в
 * подсказке при наведении: разница между «долго на CPU» и «быстро на
 * соседнем хосте» решает, стоит ли вообще нажимать.
 */
function EmbedderPicker({ choices, value, onChange }: EmbedderPickerProps) {
  const { t } = useTranslation();
  const chosen = choices.find((choice) => choice.key === value) ?? choices[0];
  if (!chosen) {
    return null;
  }

  return (
    <label className="mt-3 block space-y-1.5">
      <span className="case-label">{t("index.embedderLabel")}</span>
      <select
        value={chosen.key}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-case border border-tweed-dim bg-ink-sunken px-2 py-1.5 font-mono text-[12px] text-paper"
      >
        {choices.map((choice) => (
          <option key={choice.key} value={choice.key}>
            {choice.title}
          </option>
        ))}
      </select>
      {chosen.note ? (
        <span className="block text-[11px] leading-snug text-paper-dim">{chosen.note}</span>
      ) : null}
    </label>
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
  const { t } = useTranslation();
  if (!isConfirming) {
    return (
      <button
        type="button"
        onClick={onAsk}
        className={`${BUTTON} card-action-danger`}
      >
        {t("index.deleteIndex")}
      </button>
    );
  }

  return (
    <span className="flex items-center gap-2">
      <span className="case-label text-dismissed">{t("index.deleteConfirm")}</span>
      <button
        type="button"
        onClick={onDelete}
        disabled={isPending}
        className={`${BUTTON} card-action-danger border-dismissed text-dismissed ${
          isPending ? "card-action-busy" : ""
        }`}
      >
        {isPending ? t("index.deleting") : t("index.delete")}
      </button>
      <button
        type="button"
        onClick={onDismiss}
        className={BUTTON}
      >
        {t("common.cancel")}
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
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onCancel}
      disabled={isPending}
      className={`group/cancel ${BUTTON} card-action-danger card-action-busy`}
    >
      <span className="group-hover/cancel:hidden">{isPending ? t("index.cancelling") : label}</span>
      <span className="hidden group-hover/cancel:inline">{t("index.cancelAction")}</span>
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
const NOTED_STAGES = ["parsing", "storing", "linking", "embedding"] as const;

type NotedStage = (typeof NOTED_STAGES)[number];

function isNotedStage(stage: string): stage is NotedStage {
  return (NOTED_STAGES as readonly string[]).includes(stage);
}

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
  const { t } = useTranslation();
  const stage = state?.stage ?? "parsing";
  const title = stageTitle(t, state) ?? t("index.defaultStage");
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
        {measured
          ? t("index.progressOf", {
              done: measured.done,
              total: measured.total,
              percent: measured.percent,
            })
          : ""}
        <Elapsed since={state?.started_at ?? null} />
      </p>

      {isNotedStage(stage) ? (
        <p className="mt-1 text-[12px] text-paper-dim">{t(`index.stageNote.${stage}`)}</p>
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
 * Двигается она пачками раз в полминуты, и между прыжками счётчик времени —
 * единственное, что отличает работу от остановки. Отсчёт идёт от конца
 * разбора: досчёт начинается сразу за ним.
 * Без неё индекс выглядит собранным, хотя поиск по смыслу ещё не работает —
 * и человек делает вывод о качестве по неполному индексу.
 *
 * Рядом сказано, из чего состоит индекс: два слоя видны только изнутри,
 * а снаружи «векторы 12%» не объясняет ни что уже работает, ни чего ждать.
 */
function Vectors({ state }: VectorsProps) {
  const { t } = useTranslation();
  const { chunks, embedded } = state.vectors;
  const percent = Math.min(100, Math.round((embedded / chunks) * 100));
  const stalled = Boolean(state.failure_reason);
  const idle = !state.is_embedding && !stalled;

  return (
    <div className="mt-3">
      <div className="h-1 overflow-hidden bg-tweed-dim">
        <div
          className={`h-full transition-all duration-500 ${stalled ? "bg-critical" : "bg-brass"}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="case-label mt-1.5">
        {t("index.vectors", { embedded, chunks, percent })}
        {stalled ? t("index.stalled") : idle ? t("index.idle") : ""}
        {state.is_embedding ? <Elapsed since={state.finished_at} /> : null}
      </p>
      {stalled ? (
        <p className="mt-1.5 text-[13px] text-critical">{state.failure_reason}</p>
      ) : null}
      <p className="mt-1 text-[12px] leading-relaxed text-paper-dim">
        {t("index.layers")}
        {stalled
          ? t("index.stalledAdvice")
          : idle
            ? t("index.idleAdvice")
            : t("index.embeddingAdvice")}
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
 * требует терпения, отсутствующий — запуска. Сервер заглядывает в очередь
 * и называет, за кем стоит сборка и сколько та уже идёт; пустая очередь
 * при ожидающем снапшоте — единственный признак того, что воркера нет,
 * и только тогда подсказывается команда запуска.
 */
function Queued({ state }: QueuedProps) {
  const { t } = useTranslation();
  if (state?.is_embedding) {
    return (
      <p className="mt-2 text-[13px] text-paper-dim">
        {t("index.queuedEmbedding")}
      </p>
    );
  }

  if (state?.queue) {
    return (
      <p className="mt-2 text-[13px] text-paper-dim">
        {state.queue.busy_with
          ? t("index.queuedBehind", {
              name: state.queue.busy_with,
              duration: formatDuration(t, secondsSince(state.queue.busy_since)),
              position: state.queue.position,
            })
          : t("index.queuedBehindUnknown", { position: state.queue.position })}{" "}
        {t("index.queuedBehindHint")}
      </p>
    );
  }

  return (
    <p className="mt-2 text-[13px] text-paper-dim">
      {t("index.queued")}
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
  const { t } = useTranslation();

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  if (!since) {
    return null;
  }

  const seconds = Math.max(0, Math.floor((now - new Date(since).getTime()) / 1000));
  return <span>{t("index.elapsed", { duration: formatDuration(t, seconds) })}</span>;
}

function secondsSince(since: string | null): number {
  if (!since) {
    return 0;
  }
  return Math.max(0, Math.floor((Date.now() - new Date(since).getTime()) / 1000));
}

function formatDuration(t: TFunction, seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  if (minutes < 1) {
    return t("duration.seconds", { count: seconds });
  }
  if (minutes < 60) {
    return t("duration.minutesSeconds", {
      minutes,
      seconds: String(seconds % 60).padStart(2, "0"),
    });
  }
  return t("duration.hoursMinutes", {
    hours: Math.floor(minutes / 60),
    minutes: String(minutes % 60).padStart(2, "0"),
  });
}

function isBusy(state: State | undefined): boolean {
  return state?.status === "pending" || state?.status === "running";
}

function describe(t: TFunction, state: State | undefined, isStarting: boolean): string {
  if (isStarting) {
    return t("index.describe.queueing");
  }
  if (state?.status === "pending") {
    return t("index.describe.waitingWorker");
  }
  if (state?.status === "running") {
    return t("index.describe.building");
  }
  if (state?.status === "failed") {
    return t("index.describe.failed");
  }
  if (!state?.is_ready || !state.stats) {
    return state?.context_ready
      ? t("index.describe.previous", { count: state.totals.files })
      : t("index.describe.notBuilt");
  }

  const when = state.finished_at
    ? t("index.describe.builtAt", { date: formatDateTime(state.finished_at) })
    : "";
  return (
    t("index.describe.summary", {
      count: state.stats.files_total,
      sha: shortSha(state.commit_sha ?? ""),
    }) + when
  );
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

/**
 * Считаются ли векторы прямо сейчас — по слову сервера, не по доле.
 *
 * Неполное покрытие само по себе не признак счёта: векторы могли быть
 * посчитаны другой моделью, а досчёт — оборваться. Опрашивать сервер
 * дальше есть смысл только пока он сам говорит, что считает.
 */
function vectorsAdvancing(state: State | undefined): boolean {
  return Boolean(state?.is_embedding);
}
